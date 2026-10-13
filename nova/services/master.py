from sqlalchemy import select
from nova.models import Account, BookingEvent, Lead, Party, Project, Setting, Unit, User, Voucher
from nova.services.common import BusinessError, ROLES, audit, existing, lock, money, require


def save_project(session, actor, **values):
    require(session, actor, 'master')
    if not values.get('name', '').strip() or not values.get('number', '').strip():
        raise BusinessError('Project number and name are required.')
    obj = Project(**values)
    session.add(obj)
    audit(session, actor, 'create', obj, values)
    return obj


def save_party(session, actor, **values):
    user = existing(session, User, actor)
    require(session, actor, 'sales' if user.role == 'Sales' else 'master')
    if values.get('kind') not in ('Customer', 'Vendor', 'Contractor', 'Dealer', 'Landowner'):
        raise BusinessError('Choose a valid party type.')
    if user.role == 'Sales' and values['kind'] != 'Customer':
        raise BusinessError('Sales users can create customers only.')
    if not values.get('name', '').strip():
        raise BusinessError('Party name is required.')
    obj = Party(**values)
    session.add(obj)
    audit(session, actor, 'create', obj, {'name': obj.name, 'kind': obj.kind})
    return obj


def save_unit(session, actor, **values):
    require(session, actor, 'master')
    existing(session, Project, values['project_id'])
    if not values.get('number', '').strip():
        raise BusinessError('Unit number is required.')
    values['price'] = money(values['price'])
    obj = Unit(**values)
    session.add(obj)
    audit(session, actor, 'create', obj, values)
    return obj


def set_unit_price(session, actor, unit_id, value):
    require(session, actor, 'master')
    obj = lock(session, Unit, unit_id)
    if obj.status != 'Available':
        raise BusinessError('Prices can be changed only for available units.')
    old = obj.price
    obj.price = money(value)
    audit(session, actor, 'price_update', obj, {'old': old, 'new': obj.price})


def save_account(session, actor, **values):
    require(session, actor, 'master')
    if not values.get('code', '').strip():
        from nova.services.numbering import next_number
        values['code'] = next_number(session, 'AC')
    if values.get('kind') not in ('Asset', 'Liability', 'Equity', 'Income', 'Expense'):
        raise BusinessError('Choose a valid account type.')
    if not values.get('code', '').strip() or not values.get('name', '').strip():
        raise BusinessError('Account code and name are required.')
    if values.get('parent_id'):
        parent = existing(session, Account, values['parent_id'])
        if not parent.is_group or parent.kind != values['kind']:
            raise BusinessError('The parent must be a group of the same account type.')
    if values.get('is_cash') and (values['kind'] != 'Asset' or values.get('is_group')):
        raise BusinessError('Cash/bank accounts must be posting asset accounts.')
    from nova.models import RetiredCode
    if session.get(RetiredCode, 'account:' + values['code']):
        raise BusinessError('This account code is retired and cannot be reused.')
    obj = Account(**values)
    session.add(obj)
    audit(session, actor, 'create', obj, values)
    return obj


def save_user(session, actor, email, name, role, active=True):
    require(session, actor, 'users')
    email = email.strip().lower()
    if '@' not in email or not name.strip() or role not in ROLES:
        raise BusinessError('Valid email, name, and role are required.')
    obj = session.scalar(select(User).where(User.email == email))
    if obj and obj.id == actor and (role != 'Admin' or not active):
        raise BusinessError('You cannot remove your own administrator access.')
    if not obj:
        obj = User(email=email, name=name, role=role, active=active)
        session.add(obj)
    else:
        obj.name, obj.role, obj.active = name, role, active
    audit(session, actor, 'save_user', obj, {'email': email, 'role': role, 'active': active})
    return obj


def close_period(session, actor, through):
    require(session, actor, 'users')
    from nova.services.common import business_today
    if through > business_today():
        raise BusinessError('The closing date cannot be in the future.')
    if session.bind.dialect.name == 'sqlite':
        from sqlalchemy import update
        session.execute(update(Setting).where(Setting.key == 'schema_version').values(value=Setting.value))
    else:
        session.scalar(select(Setting).where(Setting.key == 'schema_version').with_for_update())
    if session.scalar(select(Voucher.id).where(Voucher.date <= through, Voucher.status == 'Pending')):
        raise BusinessError('Resolve pending vouchers before closing this period.')
    # An approval posts on the request date, so a pending request inside the period would become impossible to approve.
    if session.scalar(select(BookingEvent.id).where(BookingEvent.date <= through, BookingEvent.status == 'Pending')):
        raise BusinessError('Resolve pending transfer and cancellation requests before closing this period.')
    obj = session.get(Setting, 'closed_through')
    if obj and obj.value and through.isoformat() <= obj.value:
        raise BusinessError('The closing date must advance beyond the current closed period.')
    if not obj:
        obj = Setting(key='closed_through', value=through.isoformat())
        session.add(obj)
    else:
        obj.value = through.isoformat()
    from nova.models import Audit
    session.add(Audit(actor_id=actor, action='close_period', entity='settings', entity_id='closed_through', detail=through.isoformat()))


def save_lead(session, actor, **values):
    user = existing(session, User, actor)
    require(session, actor, 'sales' if user.role == 'Sales' else 'master')
    existing(session, Project, values['project_id'])
    if not values.get('name', '').strip():
        raise BusinessError('Lead name is required.')
    obj = Lead(**values)
    session.add(obj)
    audit(session, actor, 'create', obj, values)
    return obj


def update_lead(session, actor, lead_id, stage, notes, followup):
    user = existing(session, User, actor)
    require(session, actor, 'sales' if user.role == 'Sales' else 'master')
    if stage not in ('New', 'Contacted', 'Interested', 'Booked', 'Lost'):
        raise BusinessError('Choose a valid lead stage.')
    obj = existing(session, Lead, lead_id)
    obj.stage, obj.notes, obj.next_followup = stage, notes, followup
    audit(session, actor, 'update', obj, {'stage': stage, 'notes': notes, 'followup': followup})


def edit_master(session, actor, model, record_id, values):
    require(session, actor, 'master')
    allowed = {
        Project: {'name', 'owner', 'area', 'description', 'terms'},
        Party: {'name', 'relation', 'identity', 'phone', 'email', 'city', 'province', 'address'},
        Unit: {'category', 'floor', 'feature', 'area', 'reference', 'description'},
    }
    if model not in allowed or not values or not set(values).issubset(allowed[model]):
        raise BusinessError('These fields cannot be changed using master record editing.')
    if 'name' in values and not values['name'].strip():
        raise BusinessError('Name is required.')
    obj = lock(session, model, record_id)
    before = {key: getattr(obj, key) for key in values}
    for key, value in values.items():
        setattr(obj, key, value)
    audit(session, actor, 'edit_master', obj, {'before': before, 'after': values})
    return obj
