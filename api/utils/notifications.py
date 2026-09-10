from api.config import supabase

def send_notification(target_role, target_user_id, notif_type, title, description, metadata=None):
    """
    Sends a notification by inserting it into the system_notifications table.
    Ensures that a user only has a maximum of 30 notifications.
    """
    if metadata is None:
        metadata = {}
    
    metadata['target_role'] = target_role
    if target_user_id:
        metadata['target_user_id'] = target_user_id
        
    try:
        # Insert the new notification
        supabase.table('system_notifications').insert({
            "type": notif_type,
            "title": title,
            "description": description,
            "metadata": metadata
        }).execute()
        
        # Auto-delete logic: Keep only the latest 30 notifications for this user/role combo
        if target_user_id:
            # We can only delete by matching the metadata column roughly or fetching and deleting
            # Since Supabase python client doesn't easily do raw SQL for json filtering in deletes,
            # we fetch the user's notifications, keep 30, and delete the rest.
            res = supabase.table('system_notifications')\
                .select('id, metadata')\
                .order('created_at', desc=True)\
                .limit(200)\
                .execute()
                
            user_notifs = [n for n in (res.data or []) if str(n.get('metadata', {}).get('target_user_id')) == str(target_user_id)]
            
            if len(user_notifs) > 30:
                notifs_to_delete = user_notifs[30:]
                for n in notifs_to_delete:
                    supabase.table('system_notifications').delete().eq('id', n['id']).execute()
                    
    except Exception as e:
        print(f"Error sending notification: {e}")
