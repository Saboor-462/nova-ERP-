import html
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
LOGO = ROOT / 'assets/nova_logo.jpeg'
BUSINESS = 'NOVA BUSINESS CENTRE'


def brand_header(title, subtitle=''):
    left, right = st.columns([1, 7])
    if LOGO.exists():
        left.image(str(LOGO), width=105)
    with right:
        st.markdown(f'<div class="nova-heading"><span class="nova-eyebrow">{BUSINESS}</span><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>', unsafe_allow_html=True)


def login_brand():
    st.markdown('<style>[data-testid="stSidebar"]{display:none}.block-container{max-width:620px!important;padding-top:4rem!important}</style>', unsafe_allow_html=True)
    cols = st.columns([1, 1, 1])
    if LOGO.exists():
        cols[1].image(str(LOGO), width='stretch')
    st.title('Welcome to Nova ERP')
    st.caption('Sign in to manage projects, property accounts, and collections.')


def theme():
    st.markdown('''<style>
    .block-container{padding-top:1.5rem;max-width:1500px}
    [data-testid="stSidebar"]{background:#13283d;border-right:3px solid #cca431}
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
    [data-testid="stSidebar"] label,[data-testid="stSidebar"] h1{color:#edf3f8}
    [data-testid="stSidebar"] [data-baseweb="select"] *{color:#13283d}
    [data-testid="stMetric"]{padding:18px;background:white;border:1px solid #e1e7ef;border-top:3px solid #cba334;border-radius:10px;box-shadow:0 3px 12px #11243a08}
    [data-testid="stMetricLabel"]{color:#52667d}
    h1,h2,h3{color:#16314b}
    .nova-eyebrow{color:#9a761c;font-size:.78rem;font-weight:700;letter-spacing:.15rem}
    .nova-heading h1{margin:4px 0;font-size:2rem}.nova-heading p{color:#61728a;margin:0 0 18px}
    [data-testid="stForm"]{border-radius:12px;background:#fff;border:1px solid #dfe7f0}
    </style>''', unsafe_allow_html=True)
