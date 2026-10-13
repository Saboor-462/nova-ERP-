import streamlit as st
from sqlalchemy import select
from nova.models import User


def identify(factory, config):
    if config['mode'] == 'demo' or config.get('auth_method') == 'password':
        from nova.services.security import authenticate, session_user, logout
        from nova.branding import login_brand
        raw = st.session_state.get('nova_session')
        actor = session_user(factory, raw)
        if actor:
            from nova.ui.common import md_escape
            st.sidebar.caption(f'{md_escape(actor.name)} · {actor.role}')
            if st.sidebar.button('Sign out'):
                logout(factory, raw)
                st.session_state.clear()
                st.rerun()
            return actor
        if raw:
            st.session_state.clear()
        login_brand()
        with st.form('login'):
            email = st.text_input('Email', key='login_email')
            password = st.text_input('Password', type='password', key='login_password')
            submitted = st.form_submit_button('Sign in', type='primary', width='stretch')
        if submitted:
            raw, error = authenticate(factory, email, password)
            if raw:
                st.session_state['nova_session'] = raw
                st.rerun()
            else:
                st.error(error)
        st.caption('First run: use setup_admin_windows.bat to create your administrator. Passwords are set on your own computer.')
        st.stop()
    try:
        auth_configured = 'auth' in st.secrets
    except FileNotFoundError:
        auth_configured = False
    if not auth_configured:
        st.error('Sign-in is not configured. Add the [auth] section to the Streamlit secrets (see docs/SETUP.md).')
        st.stop()
    if not st.user.is_logged_in:
        st.title('Nova ERP')
        st.write('Sign in with your authorized office account.')
        if st.button('Sign in', type='primary'):
            st.login()
        st.stop()
    email = str(st.user.get('email', '')).strip().lower()
    # Require an OIDC-verified email; Entra deployments may need a provider-specific mapping.
    verified = st.user.get('email_verified', False) is True
    if not email or not verified:
        st.error('A verified email claim is required. Check the configured identity provider.')
        if st.button('Sign out'):
            st.logout()
        st.stop()
    with factory() as session:
        actor = session.scalar(select(User).where(User.email == email, User.active == True))
    if actor is None:
        st.error('Your account is not authorized. Ask the ERP administrator to add your email.')
        if st.button('Sign out'):
            st.logout()
        st.stop()
    from nova.ui.common import md_escape
    st.sidebar.caption(f'{md_escape(actor.name)} · {actor.role}')
    if st.sidebar.button('Sign out'):
        st.logout()
    return actor
