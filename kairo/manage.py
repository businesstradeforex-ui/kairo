"""Administration Kairo.

  python3 manage.py create-user [identifiant] [--role owner|user|viewer|admin]
  python3 manage.py list-users
  python3 manage.py delete-user <identifiant>
  python3 manage.py agent-token
  python3 manage.py rotate-agent-token
  python3 manage.py create-token <nom> read,params,orders,ui
  python3 manage.py revoke-token <id>

Le mot de passe n'est jamais passé en argument (invite, ou MEMEDESK_PASSWORD pour Docker/tests).
Le premier compte peut être propriétaire. Il n'existe aucun mot de passe par défaut.
"""
import getpass, os, sys
import webauth

def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__); return 0
    cmd = argv[0]
    role = "user"
    if "--role" in argv:
        i = argv.index("--role")
        role = argv[i + 1] if i + 1 < len(argv) else ""
        argv = argv[:i] + argv[i + 2:]
    if cmd == "create-user":
        if role not in webauth.ROLES:
            print("Rôle invalide : owner, user, viewer ou admin."); return 1
        user = argv[1] if len(argv) > 1 else input("Identifiant : ").strip()
        pw = os.environ.get("MEMEDESK_PASSWORD")
        if not pw:
            pw = getpass.getpass("Mot de passe (10 caractères min.) : ")
            if pw != getpass.getpass("Confirmez : "):
                print("Les mots de passe ne correspondent pas."); return 1
        try:
            webauth.set_password(user, pw, role)
        except ValueError as e:
            print(f"Erreur : {e}"); return 1
        print(f"Compte « {user} » enregistré (rôle : {role})."); return 0
    if cmd == "list-users":
        c = webauth.wdb()
        for r in c.execute("SELECT username, role, email, created FROM users ORDER BY id"):
            print(f"{r['username']:<24} {(r['role'] or ''):<8} {r['email'] or '-':<32} {r['created']}")
        return 0
    if cmd == "delete-user" and len(argv) > 1:
        c = webauth.wdb()
        row = c.execute("SELECT id, role FROM users WHERE username=?", (argv[1],)).fetchone()
        if row and row["role"] == "owner":
            print("Refusé : ne supprimez pas le propriétaire avec cette commande."); return 1
        c.execute("DELETE FROM users WHERE username=?", (argv[1],))
        if row:
            c.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        c.commit(); print("Supprimé."); return 0
    if cmd == "agent-token":
        print(webauth.ensure_agent_token()); return 0
    if cmd == "rotate-agent-token":
        c = webauth.wdb()
        c.execute("UPDATE agent_tokens SET revoked=1 WHERE name='bootstrap'")
        c.commit(); c.close()
        try:
            os.remove(webauth.AGENT_TOKEN_FILE)
        except FileNotFoundError:
            pass
        path = webauth.ensure_agent_token()
        print(path); return 0
    if cmd == "create-token" and len(argv) > 2:
        raw = webauth.create_agent_token(argv[1], [s for s in argv[2].split(",") if s])
        print("Jeton (affiché une seule fois) :")
        print(raw)
        return 0
    if cmd == "revoke-token" and len(argv) > 1:
        webauth.revoke_agent_token(argv[1]); print("Révoqué."); return 0
    print(__doc__); return 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
