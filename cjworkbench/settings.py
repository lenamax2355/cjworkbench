import json
import os
import sys
from os.path import abspath, dirname, join, normpath
from typing import Dict, Optional

from dotenv import load_dotenv

from cjworkbench.i18n import default_locale, supported_locales
from server.settingsutils import workbench_user_display

if sys.version_info[0] < 3:
    raise RuntimeError("CJ Workbench requires Python 3")

SITE_ID = 1

# How many columns can the client side display?
# Current, we limit how many the client will display because react-data-grid
# is terribly slow at >10 columns.
MAX_COLUMNS_PER_CLIENT_REQUEST = 100

MIN_AUTOFETCH_INTERVAL = 300  # seconds between cron autofetches

MAX_BYTES_FETCHES_PER_STEP = 1024 * 1024 * 1024
"""How much space can a Step's FetchResults consume?

When storing a new FetchResult, we delete old FetchResults that exceed this
limit.
"""

MAX_N_FETCHES_PER_STEP = 30
"""Maximum number of fetch outputs we'll store on a given Step.

When storing a new FetchResult, we delete old FetchResults that exceed this
limit.
"""

MAX_N_FILES_PER_STEP = 30
"""Maximum number of files we'll store on a given Step.

When storing a new File, we delete old Files that exceed this limit.
"""

MAX_BYTES_FILES_PER_STEP = 2 * 1024 * 1024 * 1024
"""How much space can a Step's Files consume?

When storing a new File, we delete old Files that exceed this limit.
"""


# ----- App Boilerplate -----

# Build paths inside the project like this: os.path.join(BASE_DIR, ...)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Configuration below uses these instead of BASE_DIR
DJANGO_ROOT = dirname(dirname(abspath(__file__)))

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/1.10/howto/deployment/checklist/

# SECURITY WARNING: don't run with debug turned on in production!
if "CJW_PRODUCTION" in os.environ:
    DEBUG = not os.environ["CJW_PRODUCTION"]
else:
    DEBUG = True

I_AM_TESTING = "test" in sys.argv

if "CJW_FORCE_SSL" in os.environ:
    SECURE_SSL_REDIRECT = bool(os.environ["CJW_FORCE_SSL"])

DEFAULT_FROM_EMAIL = "Workbench <hello@workbenchdata.com>"

# SECRET_KEY
try:
    SECRET_KEY = os.environ["CJW_SECRET_KEY"]
except KeyError:
    sys.exit("Must set CJW_SECRET_KEY")

# DATABASES
try:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql_psycopg2",
            "NAME": "cjworkbench",
            "USER": "cjworkbench",
            "HOST": os.environ["CJW_DB_HOST"],
            "PASSWORD": os.environ["CJW_DB_PASSWORD"],
            "PORT": "5432",
            "CONN_MAX_AGE": 30,
            "TEST": {"SERIALIZE": False, "NAME": "cjworkbench", "MIGRATE": False},
        }
    }
except KeyError:
    sys.exit("Must set CJW_DB_HOST and CJW_DB_PASSWORD")

N_SYNC_DATABASE_CONNECTIONS = 3
"""
Number of simultaneous Django database transactions.

Smaller numbers give higher throughput on the database. There are no known
"slow" database queries in Workbench; but if we found some, we'd want to
increase this number so they don't block other requests.
"""
# (Any block of Workbench code with a "cooperative_lock" consumes a database
# transaction until finish. Currently, we lock during S3 transfers. TODO make
# cooperative_lock() use PgLocker instead.)
#
# (PgLocker connections do not count against SYNC_DATABASE_CONNECTIONS.)

# RabbitMQ
try:
    RABBITMQ_HOST = os.environ["CJW_RABBITMQ_HOST"]
except KeyError:
    sys.exit("Must set CJW_RABBITMQ_HOST")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_rabbitmq.core.RabbitmqChannelLayer",
        "CONFIG": {"host": RABBITMQ_HOST, "local_capacity": 2000},
    }
}

# For django-allauth
ACCOUNT_ADAPTER = "cjworkbench.allauth_account_adapter.AccountAdapter"
SOCIALACCOUNT_ADAPTER = "cjworkbench.allauth_account_adapter.SocialAccountAdapter"

# EMAIL_BACKEND
#
# In Production, sets ACCOUNT_ADAPTER, SENDGRID_TEMPLATE_IDS
if DEBUG or os.environ.get("CJW_MOCK_EMAIL"):
    EMAIL_BACKEND = "django.core.mail.backends.filebased.EmailBackend"
    EMAIL_FILE_PATH = os.path.join(BASE_DIR, "local_mail")
else:
    if "CJW_SENDGRID_API_KEY" not in os.environ:
        sys.exit("Must set CJW_SENDGRID_API_KEY in production")

    EMAIL_HOST = "smtp.sendgrid.net"
    EMAIL_HOST_USER = "apikey"
    EMAIL_HOST_PASSWORD = os.environ["CJW_SENDGRID_API_KEY"]
    EMAIL_PORT = 587
    EMAIL_USE_TLS = True

    # EMAIL_BACKEND = "sgbackend.SendGridBackend"
    # # ACCOUNT_ADAPTER is specifically for sendgrid and nothing else
    # ACCOUNT_ADAPTER = "cjworkbench.views.account_adapter.WorkbenchAccountAdapter"

    # if not all(
    #     x in os.environ
    #     for x in ["CJW_SENDGRID_CONFIRMATION_ID", "CJW_SENDGRID_PASSWORD_RESET_ID"]
    # ):
    #     sys.exit("Must set Sendgrid template IDs for all system emails")

    # SENDGRID_API_KEY = os.environ["CJW_SENDGRID_API_KEY"]

    # SENDGRID_TEMPLATE_IDS = {
    #     "account/email/email_confirmation": os.environ["CJW_SENDGRID_CONFIRMATION_ID"],
    #     "account/email/email_confirmation_signup": os.environ[
    #         "CJW_SENDGRID_CONFIRMATION_ID"
    #     ],
    #     "account/email/password_reset_key": os.environ[
    #         "CJW_SENDGRID_PASSWORD_RESET_ID"
    #     ],
    # }

if "HTTPS" in os.environ and os.environ["HTTPS"] == "on":
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    USE_X_FORWARDED_HOST = True
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

ALLOWED_HOSTS = ["*"]

# Application definition
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    # These providers appear in _ALL ENVIRONMENTS_ for now.
    # see https://github.com/pennersr/django-allauth/issues/2343
    # ... so don't add a provider that doesn't belong on production!
    # (On dev/unittest/integrationtest, the buttons will appear but
    # clicking one will get a 404 page unless the SocialApp is added.)
    "allauth.socialaccount.providers.facebook",
    "allauth.socialaccount.providers.google",
    "cjworkbench",
    "cron",
    "fetcher",
    "renderer",
    "server",
]

# Disable Django migrations (we use Flyway)
MIGRATION_MODULES = {k: None for k in INSTALLED_APPS}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "cjworkbench.middleware.i18n.SetCurrentLocaleMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

SESSION_ENGINE = "django.contrib.sessions.backends.db"

ROOT_URLCONF = "cjworkbench.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # 'DIRS': [os.path.join(BASE_DIR, 'templates')],
        "DIRS": ["templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "cjworkbench.i18n.templates.context_processor",
            ]
        },
    }
]

ASGI_APPLICATION = "cjworkbench.asgi.application"


# Password validation
# https://docs.djangoproject.com/en/1.10/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LOGIN_URL = "/account/login"
LOGIN_REDIRECT_URL = "/workflows"

# TODO nix USE_I18N
#
# Currently, we only use it for Django login-form error translation. We have our
# own i18n system for everything else. [2020-12-22] Django + async views won't
# work with i18n, and we must avoid touching Django's `activate()` in async
# views.
LANGUAGE_CODE = default_locale
USE_I18N = True
USE_L10N = True

TIME_ZONE = "UTC"

LANGUAGES = [(locale, locale) for locale in supported_locales]

LOCALE_PATHS = (os.path.join(BASE_DIR, "assets", "locale"),)

# We break with Django tradition here and serve files from a different URL
# even in DEBUG mode. Anything else would be obfuscation.
STATIC_URL = os.environ.get("STATIC_URL", "http://localhost:8003/")

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "plaintext": {
            "format": ("%(levelname)s %(asctime)s %(name)s %(thread)d %(message)s")
        },
        "json": {"class": "server.logging.json.JsonFormatter"},
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "plaintext" if DEBUG else "json",
        }
    },
    "loggers": {
        "": {"handlers": ["console"], "level": "DEBUG", "propagate": True},
        # It's nice to have level=DEBUG, but we have experience with lots of
        # modules that we think are now better off as INFO.
        "asyncio": {"level": "INFO"},
        "botocore": {"level": "INFO"},
        "carehare": {"level": "INFO"},
        "channels_rabbitmq": {"level": "INFO"},
        "intercom": {"level": "INFO"},
        "oauthlib": {"level": "INFO"},
        "urllib3": {"level": "INFO"},
        "requests_oauthlib": {"level": "INFO"},
        "s3transfer": {"level": "INFO"},
        "django.request": {
            # Django prints WARNINGs for 400-level HTTP responses. That's
            # wrong: our code is _meant_ to output 400-level HTTP responses in
            # some cases -- that's exactly why 400-level HTTP responses exist!
            # Ignore those WARNINGs and only log ERRORs.
            "level": "ERROR"
        },
        # DEBUG only gets messages when settings.DEBUG==True
        "django.db.backends": {"level": "INFO"},
        "websockets.protocol": {"level": "INFO"},
        "websockets.server": {"level": "INFO"},
        "cjwstate.models.module_registry": {
            "level": ("WARNING" if I_AM_TESTING else "INFO")
        },
        "cjworkbench.pg_render_locker": {"level": "INFO"},
        "stripe": {"level": "INFO"},
    },
}

# User accounts

ACCOUNT_USER_MODEL_USERNAME_FIELD = "username"
ACCOUNT_EMAIL_REQUIRED = True
ACCOUNT_EMAIL_VERIFICATION = "mandatory"
ACCOUNT_USERNAME_REQUIRED = False
ACCOUNT_AUTHENTICATION_METHOD = "email"
ACCOUNT_USER_DISPLAY = workbench_user_display
ACCOUNT_SIGNUP_FORM_CLASS = "cjworkbench.forms.signup.WorkbenchSignupForm"

AUTHENTICATION_BACKENDS = ["allauth.account.auth_backends.AuthenticationBackend"]

# Third party services
OAUTH_SERVICES: Dict[str, Dict[str, Optional[str]]] = {}
"""
service => parameters. See requests-oauthlib docs
"""


# Stripe is configured via environment variables; but in dev mode, a file
# "stripe.json" can serve as fallback.
try:
    load_dotenv(os.path.join(BASE_DIR, "stripe.env"))
except FileNotFoundError:
    # This is normal
    pass


if "STRIPE_API_KEY" in os.environ:
    STRIPE_API_KEY = os.environ["STRIPE_API_KEY"]
    STRIPE_PUBLIC_API_KEY = os.environ["STRIPE_PUBLIC_API_KEY"]
    STRIPE_WEBHOOK_SIGNING_SECRET = os.environ["STRIPE_WEBHOOK_SIGNING_SECRET"]


def _maybe_load_oauth_service(
    name: str, env_var_name: str, default_path_name: str, parse
):
    path = os.environ.get(env_var_name)
    if not path:
        path = os.path.join(BASE_DIR, default_path_name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        # This is normal: frontend+fetcher get OAuth, but cron+renderer do not
        return
    config = parse(data)
    OAUTH_SERVICES[name] = config


# Google, for Google Drive module
def _parse_google_oauth(d):
    return {
        "class": "OAuth2",
        "client_id": d["web"]["client_id"],
        "client_secret": d["web"]["client_secret"],
        "auth_url": d["web"]["auth_uri"],
        "token_url": d["web"]["token_uri"],
        "refresh_url": d["web"]["token_uri"],
        "redirect_url": d["web"]["redirect_uris"][0],
        "scope": " ".join(
            [
                "openid",
                "https://www.googleapis.com/auth/drive.readonly",
                "https://www.googleapis.com/auth/userinfo.email",
            ]
        ),
    }


_maybe_load_oauth_service(
    "google", "CJW_GOOGLE_CLIENT_SECRETS", "client_secret.json", _parse_google_oauth
)

# Intercom, for Intercom module
def _parse_intercom_oauth(d):
    return {
        "class": "OAuth2",
        "client_id": d["client_id"],
        "client_secret": d["client_secret"],
        "auth_url": "https://app.intercom.com/oauth",
        "token_url": "https://api.intercom.io/auth/eagle/token",
        "refresh_url": None,
        "redirect_url": d["redirect_url"],
        "scope": "",  # set on Intercom app, not in our request
    }


_maybe_load_oauth_service(
    "intercom",
    "CJW_INTERCOM_CLIENT_SECRETS",
    "intercom_secret.json",
    _parse_intercom_oauth,
)

# Twitter, for Twitter module
def _parse_twitter_oauth(d):
    return {
        "class": "OAuth1a",
        "consumer_key": d["key"],
        "consumer_secret": d["secret"],
        "auth_url": "https://api.twitter.com/oauth/authorize",
        "request_token_url": "https://api.twitter.com/oauth/request_token",
        "access_token_url": "https://api.twitter.com/oauth/access_token",
        "redirect_url": d["redirect_url"],
    }


_maybe_load_oauth_service(
    "twitter", "CJW_TWITTER_CLIENT_SECRETS", "twitter_secret.json", _parse_twitter_oauth
)

# Knowledge base root url, used as a default for missing help links
KB_ROOT_URL = "http://help.workbenchdata.com/"

TEST_RUNNER = "server.tests.runner.TimeLoggingDiscoverRunner"

TUS_CREATE_UPLOAD_URL = os.environ.get("TUS_CREATE_UPLOAD_URL", "")
TUS_EXTERNAL_URL_PREFIX_OVERRIDE = os.environ.get(
    "TUS_EXTERNAL_URL_PREFIX_OVERRIDE", TUS_CREATE_UPLOAD_URL
)

if "MINIO_URL" not in os.environ and "AWS_S3_ENDPOINT" not in os.environ:
    sys.exit("Must set AWS_S3_ENDPOINT")
if "MINIO_ACCESS_KEY" not in os.environ and "AWS_ACCESS_KEY_ID" not in os.environ:
    sys.exit("Must set AWS_ACCESS_KEY_ID")
if "MINIO_SECRET_KEY" not in os.environ and "AWS_SECRET_ACCESS_KEY" not in os.environ:
    sys.exit("Must set AWS_SECRET_ACCESS_KEY")
if (
    "MINIO_BUCKET_PREFIX" not in os.environ
    and "S3_BUCKET_NAME_PATTERN" not in os.environ
):
    sys.exit("Must set S3_BUCKET_NAME_PATTERN")
AWS_S3_ENDPOINT = os.environ.get("AWS_S3_ENDPOINT", os.environ.get("MINIO_URL"))
AWS_ACCESS_KEY_ID = os.environ.get(
    "AWS_ACCESS_KEY_ID", os.environ.get("MINIO_ACCESS_KEY")
)
AWS_SECRET_ACCESS_KEY = os.environ.get(
    "AWS_SECRET_ACCESS_KEY", os.environ.get("MINIO_SECRET_KEY")
)
if "S3_BUCKET_NAME_PATTERN" in os.environ:
    S3_BUCKET_NAME_PATTERN = os.environ["S3_BUCKET_NAME_PATTERN"]
elif len(os.environ["MINIO_BUCKET_PREFIX"]) > 0:
    S3_BUCKET_NAME_PATTERN = (
        os.environ["MINIO_BUCKET_PREFIX"]
        + "-%s"
        + os.environ.get("MINIO_BUCKET_SUFFIX", "")
    )
else:
    S3_BUCKET_NAME_PATTERN = "%s" + os.environ.get("MINIO_BUCKET_SUFFIX", "")
if "MINIO_STATIC_URL_PATTERN" in os.environ:
    STATIC_URL = os.environ["MINIO_STATIC_URL_PATTERN"]

LESSON_FILES_URL = "https://static.workbenchdata.com"
"""URL where we publish data for users to fetch in lessons.

[2019-11-12] Currently, this is in the production static-files URL. TODO move
it to a new bucket, because developers must write to the bucket before
deploying code that depends on it.

Why not use an environment-specific url, like STATIC_URL? Because our network
sandbox forbids fetcher modules from accessing private-use IP addresses. We
don't use internal resolvers (e.g., Docker DNS, Docker-managed /etc/hosts) and
we firewall internal IP addresses (e.g., s3, localhost). Dev,
integration-test and production all have different network setups, and we'd
need three different codepaths to make environment-specific URLs work.
"""

BIG_TABLE_ROWS_PER_TILE = 100
"""Number of rows fetched in a single request of a table.

A smaller number means more HTTP requests are needed to fill a table. A larger
number means each request returns more data -- and React renders are slower.
"""

BIG_TABLE_COLUMNS_PER_TILE = 20
"""Number of rows fetched in a single request of a table.

A smaller number means more HTTP requests are needed to fill a table. A larger
number means each request returns more data -- and React renders are slower.
"""
