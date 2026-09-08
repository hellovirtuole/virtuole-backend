import sys; sys.path.append('d:/antigravity/virtuole-platform'); from api.config import supabase
res = supabase.table('users').select('*').eq('promo_code', 'AMBHKRU').execute()
print(res.data)
