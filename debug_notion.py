import os
from notion_client import Client
from dotenv import load_dotenv

# Charge les clés
load_dotenv()
token = os.getenv("NOTION_TOKEN")

if not token:
    print("❌ Erreur : Pas de token dans le fichier .env")
    exit()

notion = Client(auth=token)

print(f"🤖 Connexion en cours avec : {token[:15]}...")

try:
    # RECHERCHE SANS FILTRE (pour contourner l'erreur de validation)
    # On demande tout, on triera après.
    response = notion.search()
    results = response.get("results")
    
    print(f"🔎 Le robot voit {len(results)} élément(s) au total.")

    # On filtre nous-mêmes en Python pour trouver les Bases de Données
    databases = [obj for obj in results if obj["object"] == "database"]

    if not databases:
        print("\n❌ PROBLÈME : Le robot ne voit AUCUNE base de données.")
        print("👉 Il a peut-être accès à la PAGE qui contient la base, mais pas à la BASE elle-même.")
        print("👉 Solution :")
        print("1. Ouvre ta base en PLEINE PAGE (pas à l'intérieur d'une autre page).")
        print("2. Menu '...' en haut à droite > Connexions > Ajoute ton intégration.")
        
        if results:
            print("\n(Info: Le robot voit quand même ces pages, donc la connexion marche :)")
            for item in results:
                print(f"   - Type: {item['object']} | ID: {item['id']}")
    else:
        print(f"\n✅ SUCCÈS ! Voici les bases accessibles :")
        for db in databases:
            db_id = db['id']
            # Tentative de récupération du titre (peut varier selon les versions)
            try:
                if "title" in db and db["title"]:
                    title = db['title'][0]['plain_text']
                else:
                    title = "Base Sans Titre"
            except:
                title = "Titre illisible"
            
            print(f"\n📂 NOM : {title}")
            print(f"🔑 ID À COPIER : {db_id}")
            print("-" * 30)
            
        print("\n👉 Copie l'ID ci-dessus et colle-le dans ton fichier .env (à la ligne DATABASE_ID)")

except Exception as e:
    print(f"❌ Erreur technique : {e}")