# Setup — Nova ERP 0.2.0

Start with README.md and UPGRADE_0_2_0.md. The old automatic sample seeding and role selector are removed from normal startup.

## Local Windows

Install Python 3.12, extract and open nova_erp, then run setup_windows.bat → setup_admin_windows.bat → run_windows.bat. Sign in at http://localhost:8501 using the email and password you set locally. No password is supplied in source.

Existing users: stop Streamlit, back up the old project/database, restore your database into a separate new installation, run python -m scripts.init_db for the backed-up upgrade, then set the administrator password. See UPGRADE_0_2_0.md for precise steps and rollback.

Local configuration defaults to the protected data/demo.db SQLite file and password login. .env.example shows optional settings. .streamlit/config.toml controls appearance. Do not commit .env or filled secrets.toml.

Create an Approver account/password under Administration before testing approvals. Creator self-approval is disabled in the interactive app, even locally.

## Online acceptance later

Use explicit APP_MODE=production, your Supabase PostgreSQL connection URL with sslmode=require, and AUTH_METHOD=oidc for the supplied Google configuration, or AUTH_METHOD=password for explicitly configured password accounts. Copy secrets.example.toml to the host's private secrets settings and replace placeholders only there. Google redirect_uri must match the deployed HTTPS URL followed by /oauth2callback, registered with the identity provider. OIDC accepts active, authorized verified-email accounts.

Initialize PostgreSQL separately. Before upgrading an existing PostgreSQL database, run python -m scripts.backup to a new .dump path and pass --postgres-backup-done to scripts.init_db after verifying that backup. The new release has not been integration-tested against Supabase or a live identity provider in this build environment.

Do not use cloud-local SQLite as long-term online business storage. Deploy source from a private Git repository, exclude actual databases/secrets/documents, and complete HTTPS, authentication, backup/restore and concurrent-user acceptance before daily business use.

## Backups

The consistent backup tool is python -m scripts.backup --output backups/your-new-backup.db for SQLite, or a .dump destination for configured PostgreSQL. Keep a protected copy on a separate device. Do not experiment with restoration over the active database.

## Official references

- https://docs.streamlit.io/develop/concepts/connections/authentication
- https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://argon2-cffi.readthedocs.io/en/stable/
