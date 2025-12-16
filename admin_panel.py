# admin_panel.py - ПОЛНОСТЬЮ СОВМЕСТИМАЯ С НОВОЙ БАЗОЙ (FIXED VERSION)
from database import Database
from datetime import datetime, timedelta


class AdminPanel:
    """Консольная админ-панель для новой версии Database (FIXED)"""

    def __init__(self):
        self.db = Database()

    def run(self):
        print("\n" + "=" * 60)
        print("AXIOM SERVER - ADMIN PANEL")
        print("=" * 60)

        while True:
            print("\nMENU:")
            print("  1. Add user")
            print("  2. Delete user (by ID)")
            print("  3. List all users")
            print("  4. View user details (by username)")
            print("  5. Deactivate user")
            print("  6. Activate user")
            print("  7. Extend subscription")
            print("  0. Exit")

            choice = input("\nSelect option: ").strip()

            if choice == "1":
                self.add_user()
            elif choice == "2":
                self.delete_user_by_id()
            elif choice == "3":
                self.list_users()
            elif choice == "4":
                self.view_user_details()
            elif choice == "5":
                self.deactivate_user()
            elif choice == "6":
                self.activate_user()
            elif choice == "7":
                self.extend_subscription()
            elif choice == "0":
                print("Exiting admin panel...")
                break
            else:
                print("Invalid option")

    def add_user(self):
        print("\nADD NEW USER")
        username = input("Username: ").strip()
        if not username:
            print("Username cannot be empty")
            return

        email = input("Email (optional): ").strip() or None
        try:
            days_input = input("Subscription days (default 30): ").strip()
            days = int(days_input) if days_input else 30
        except ValueError:
            days = 30

        api_key = self.db.add_user(username, email, days)

        if api_key:
            expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
            print("\nUSER CREATED SUCCESSFULLY!")
            print(f"   Username: {username}")
            print(f"   Email:    {email or 'N/A'}")
            print(f"   API Key:  {api_key}")
            print(f"   Expires:  {expires} ({days} days)")
            print("\nSAVE THE API KEY — it won't be shown again!")
        else:
            print("User already exists!")

    def delete_user_by_id(self):
        user_id = input("\nUser ID to delete: ").strip()
        if not user_id.isdigit():
            print("Invalid ID")
            return
        confirm = input(f"Delete user ID {user_id}? (yes/no): ").strip().lower()
        if confirm == "yes":
            self.db.delete_user(int(user_id))
            print("User deleted (if existed)")

    def list_users(self):
        print("\nALL USERS:")
        users = self.db.get_all_users()

        if not users:
            print("   No users")
            return

        print(f"\n{'ID':<4} {'Username':<18} {'Email':<22} {'Active':<8} {'Expires':<12} {'Status':<12}")
        print("-" * 90)

        now = datetime.now()
        for u in users:
            expires = datetime.fromisoformat(u['expires_at'])
            days_left = (expires - now).days
            status = "EXPIRED" if days_left < 0 else f"{days_left}d left"
            active = "Yes" if u['is_active'] else "No"
            email = u['email'] or "N/A"
            print(f"{u['id']:<4} {u['username']:<18} {email:<22} {active:<8} {u['expires_at'][:10]} {status:<12}")

        print(f"\nTotal users: {len(users)}")

    def view_user_details(self):
        username = input("\nUsername: ").strip()
        if not username:
            return

        users = self.db.get_all_users()
        user = next((u for u in users if u['username'] == username), None)

        if not user:
            print(f"User '{username}' not found")
            return

        expires = datetime.fromisoformat(user['expires_at'])
        days_left = (expires - datetime.now()).days

        print("\n" + "=" * 60)
        print(f"USER: {user['username']}")
        print("=" * 60)
        print(f"  ID:          {user['id']}")
        print(f"  Username:    {user['username']}")
        print(f"  Email:       {user['email'] or 'N/A'}")
        print(f"  API Key:     {user['api_key']}")
        print(f"  Created:     {user['created_at'][:19]}")
        print(f"  Active:      {'Yes' if user['is_active'] else 'No'}")
        print(f"  Expires:     {user['expires_at'][:19]}")

        if days_left >= 0:
            print(f"  Status:      Active ({days_left} days left)")
        else:
            print(f"  Status:      EXPIRED")

        # Показываем настройки
        settings = self.db.get_user_settings(user['id'])
        if any(settings.values()):
            print("\n  FILTER SETTINGS:")
            enabled = lambda x: "ON" if x else "OFF"
            print(f"    Avg MCAP:         {enabled(settings['enable_avg_mcap'])}  → ${settings['min_avg_mcap']:,.0f}")
            print(f"    Avg ATH MCAP:     {enabled(settings['enable_avg_ath_mcap'])}  → ${settings['min_avg_ath_mcap']:,.0f}")
            print(f"    Migrations:       {enabled(settings['enable_migrations'])}  → {settings['min_migration_percent']:.1f}%")
        else:
            print("\n  FILTER SETTINGS: All disabled / default")

        print("=" * 60)

    def deactivate_user(self):
        username = input("\nUsername to deactivate: ").strip()
        users = self.db.get_all_users()
        user = next((u for u in users if u['username'] == username), None)
        if user:
            self.db.update_user_status(user['id'], 0)
            print(f"User {username} deactivated")
        else:
            print("User not found")

    def activate_user(self):
        username = input("\nUsername to activate: ").strip()
        users = self.db.get_all_users()
        user = next((u for u in users if u['username'] == username), None)
        if user:
            self.db.update_user_status(user['id'], 1)
            print(f"User {username} activated")
        else:
            print("User not found")

    def extend_subscription(self):
        username = input("\nUsername: ").strip()
        users = self.db.get_all_users()
        user = next((u for u in users if u['username'] == username), None)
        if not user:
            print("User not found")
            return

        try:
            days = int(input("Add days: ").strip())
        except:
            print("Invalid number")
            return

        self.db.extend_subscription(user['id'], days)
        new_expires = (datetime.fromisoformat(user['expires_at']) + timedelta(days=days)).strftime("%Y-%m-%d")
        print(f"Subscription extended by {days} days → expires {new_expires}")


if __name__ == "__main__":
    admin = AdminPanel()
    admin.run()