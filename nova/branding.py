import base64
import html
from pathlib import Path

import streamlit as st


ROOT = Path(__file__).resolve().parent.parent
TRANSPARENT_LOGO = ROOT / 'assets' / 'nova_logo.png'
ORIGINAL_LOGO = ROOT / 'assets' / 'nova_logo.jpeg'
LOGO = TRANSPARENT_LOGO if TRANSPARENT_LOGO.is_file() else ORIGINAL_LOGO
BUSINESS = 'NOVA BUSINESS CENTRE'


def _logo_markup(css_class):
    if not LOGO.is_file():
        return '<span class="nova-wordmark">NOVA</span>'

    mime = 'image/png' if LOGO.suffix.lower() == '.png' else 'image/jpeg'
    encoded = base64.b64encode(LOGO.read_bytes()).decode('ascii')

    return (
        f'<img class="{html.escape(css_class, quote=True)}" '
        f'src="data:{mime};base64,{encoded}" '
        f'alt="NOVA Business Centre logo">'
    )


def sidebar_brand():
    st.sidebar.markdown(
        '<div class="nova-sidebar-brand">'
        + _logo_markup('nova-sidebar-logo')
        + '</div>',
        unsafe_allow_html=True,
    )


def brand_header(title, subtitle=''):
    st.markdown(
        '<div class="nova-page-header">'
        '<div class="nova-header-logo-wrap">'
        + _logo_markup('nova-header-logo')
        + '</div><div class="nova-heading">'
        f'<span class="nova-eyebrow">{html.escape(BUSINESS)}</span>'
        f'<h1>{html.escape(str(title))}</h1>'
        f'<p>{html.escape(str(subtitle or ""))}</p>'
        '</div></div>',
        unsafe_allow_html=True,
    )


def login_brand():
    st.markdown(
        '''<style>
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"] {
            display: none !important;
        }

        html,
        body,
        [data-testid="stApp"],
        [data-testid="stAppViewContainer"],
        [data-testid="stMain"],
        [data-testid="stHeader"],
        [data-testid="stToolbar"] {
            background: #13283d !important;
            color: #ffffff !important;
        }

        .block-container {
            max-width: 640px !important;
            padding-top: 2.5rem !important;
            padding-bottom: 2rem !important;
        }

        .nova-login-hero {
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            box-shadow: none !important;
        }

        [data-testid="stForm"] {
            background: transparent !important;
            border: none !important;
            border-radius: 0 !important;
            box-shadow: none !important;
        }

        [data-testid="stForm"] label,
        [data-testid="stForm"] label p {
            color: #ffffff !important;
        }

        [data-testid="stForm"] [data-baseweb="input"],
        [data-testid="stForm"] input {
            background: #1b354e !important;
            color: #ffffff !important;
            caret-color: #ffffff;
        }

        [data-testid="stForm"] input {
            -webkit-text-fill-color: #ffffff;
        }

        [data-testid="stForm"] [data-baseweb="input"] button {
            background: transparent !important;
            color: #ffffff !important;
        }

        [data-testid="stToolbar"] button {
            color: #ffffff !important;
        }
        </style>''',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<section class="nova-login-hero">'
        + _logo_markup('nova-login-logo')
        + '<div class="nova-login-rule"></div>'
        '<h1>Welcome to Nova ERP</h1>'
        f'<div class="nova-login-business">{html.escape(BUSINESS)}</div>'
        '<p>Sign in to manage your projects, accounts and collections.</p>'
        '</section>',
        unsafe_allow_html=True,
    )


def theme():
    st.markdown(
        '''<style>
        .block-container {
            padding-top: 4.5rem;
            padding-bottom: 2rem;
            max-width: 1500px;
        }

        [data-testid="stSidebar"] {
            background: #13283d;
            border-right: 2px solid #cba334;
        }

        [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
            padding-top: .5rem !important;
        }

        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
        [data-testid="stSidebar"] label,
        [data-testid="stSidebar"] h1,
        [data-testid="stSidebar"] h2,
        [data-testid="stSidebar"] h3 {
            color: #edf3f8;
        }

        [data-testid="stSidebar"] [data-testid="stCaptionContainer"],
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] p,
        [data-testid="stSidebar"] .st-key-nova_sidebar_footer [data-testid="stMarkdownContainer"],
        [data-testid="stSidebar"] .st-key-nova_sidebar_footer [data-testid="stMarkdownContainer"] p {
            color: #edf3f8 !important;
            opacity: 1 !important;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"],
        [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] {
            width: 100% !important;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] {
            gap: .45rem;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] {
            box-sizing: border-box;
            display: flex;
            align-items: center;
            width: 100%;
            min-height: 44px;
            margin: 0 !important;
            padding: 10px 14px;
            background: #13283d;
            border: 1px solid #cba334;
            border-radius: 9px;
            color: #edf3f8 !important;
            cursor: pointer;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] > div:first-of-type {
            display: none;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] > div:last-of-type {
            min-width: 0;
            margin: 0;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"] p {
            margin: 0;
            color: #edf3f8 !important;
            white-space: normal;
            overflow-wrap: anywhere;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:hover {
            background: #203a52;
            border-color: #e4c36f;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
            background: #25435c;
            border-color: #e4c36f;
            box-shadow: inset 3px 0 0 #e4c36f;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) p {
            color: #ffffff !important;
            font-weight: 700;
        }

        [data-testid="stSidebar"] [data-testid="stRadio"] label[data-baseweb="radio"]:has(input:focus-visible) {
            outline: 2px solid #e4c36f;
            outline-offset: 3px;
        }

        [data-testid="stSidebar"] [data-baseweb="select"] * {
            color: var(--text-color, #203347);
        }

        [data-testid="stSidebar"] [data-testid="stButton"] button {
            background: #081421 !important;
            color: #ffffff !important;
            border: 1px solid #cba334 !important;
            border-radius: 9px;
            min-height: 44px;
            width: 100%;
            font-weight: 600;
        }

        [data-testid="stSidebar"] [data-testid="stButton"] button p {
            color: #ffffff !important;
        }

        [data-testid="stSidebar"] [data-testid="stButton"] button:hover {
            background: #203a52 !important;
            border-color: #e4c36f !important;
        }

        [data-testid="stSidebar"] [data-testid="stButton"] button:focus-visible {
            outline: 2px solid #e4c36f;
            outline-offset: 3px;
        }

        .nova-sidebar-brand {
            text-align: center;
            padding: 0 0 12px;
            margin-bottom: 8px;
            border-bottom: 1px solid #cba33455;
        }

        .nova-sidebar-logo {
            display: block;
            width: 145px;
            max-width: 70%;
            height: auto;
            margin: 0 auto;
        }

        .nova-wordmark {
            color: #dfbc61;
            font-size: 2rem;
            font-weight: 700;
            letter-spacing: .15em;
        }

        .nova-page-header {
            display: flex;
            align-items: center;
            gap: 22px;
            padding: 22px 26px;
            margin-bottom: 22px;
            background: linear-gradient(120deg, #13283d, #1d3c56);
            border: 1px solid #cba33455;
            border-radius: 16px;
        }

        .nova-header-logo-wrap {
            flex: 0 0 85px;
        }

        .nova-header-logo {
            display: block;
            width: 85px;
            height: auto;
        }

        .nova-heading {
            min-width: 0;
        }

        .nova-eyebrow {
            color: #e4c36f;
            font-size: .72rem;
            font-weight: 700;
            letter-spacing: .12em;
        }

        .nova-heading h1 {
            color: #ffffff !important;
            margin: 5px 0 7px;
            padding: 0;
            font-size: clamp(1.5rem, 3vw, 2.2rem);
            line-height: 1.2;
            overflow-wrap: anywhere;
        }

        .nova-heading p {
            color: #dbe5ee;
            margin: 0;
            line-height: 1.6;
        }

        .nova-login-hero {
            text-align: center;
            padding: 28px 22px 30px;
            margin-bottom: 22px;
            background: linear-gradient(145deg, #13283d, #1d3c56);
            border: 1px solid #cba33488;
            border-radius: 20px;
        }

        .nova-login-logo {
            display: block;
            width: 170px;
            max-width: 60%;
            height: auto;
            margin: 0 auto 18px;
        }

        .nova-login-rule {
            width: 48px;
            height: 2px;
            background: #cba334;
            margin: 0 auto 18px;
        }

        .nova-login-hero h1 {
            color: #ffffff !important;
            font-size: clamp(1.7rem, 5vw, 2.5rem);
            line-height: 1.2;
            padding: 0;
            margin: 0 0 12px;
        }

        .nova-login-business {
            color: #e4c36f;
            font-size: .83rem;
            font-weight: 600;
            letter-spacing: .1em;
        }

        .nova-login-hero p {
            color: #dbe5ee;
            font-size: .95rem;
            line-height: 1.6;
            margin: 12px 0 0;
        }

        [data-testid="stMetric"] {
            padding: 18px;
            background: var(--secondary-background-color, #f4f7fb);
            border: 1px solid #8192a333;
            border-top: 3px solid #cba334;
            border-radius: 12px;
        }

        [data-testid="stMetricLabel"] {
            color: inherit;
        }

        [data-testid="stMetricValue"],
        [data-testid="stMetricValue"] > div {
            font-size: clamp(1.15rem, 2vw, 1.85rem) !important;
            line-height: 1.35;
            white-space: normal !important;
            text-overflow: clip !important;
            overflow: visible !important;
            overflow-wrap: anywhere;
            font-variant-numeric: tabular-nums;
        }

        [data-testid="stForm"] {
            border-radius: 14px;
            background: var(--background-color, transparent);
            border: 1px solid #8192a344;
        }

        @media (max-width: 640px) {
            .nova-page-header {
                gap: 14px;
                padding: 18px 16px;
            }

            .nova-header-logo-wrap {
                flex-basis: 58px;
            }

            .nova-header-logo {
                width: 58px;
            }

            .nova-eyebrow {
                font-size: .64rem;
                letter-spacing: .06em;
            }

            .nova-login-hero {
                padding: 24px 16px;
            }

            .nova-login-logo {
                width: 140px;
            }
        }
        </style>''',
        unsafe_allow_html=True,
    )
