from supabase import create_client
import os
url = os.environ.get("SUPABASE_URL", "https://fyrwiytzuxsebluygtjb.supabase.co")
key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
sb = create_client(url, key)
res = sb.auth.admin.list_users()
print([user.email for user in res])
