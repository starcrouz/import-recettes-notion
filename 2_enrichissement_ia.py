import os
import time
import json
import re
from notion_client import Client
import google.generativeai as genai
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID") # C'est ton ID de Data Source
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not all([NOTION_TOKEN, DATABASE_ID, GEMINI_API_KEY]):
    print("❌ ERREUR : Clés introuvables dans .env")
    exit()

notion = Client(auth=NOTION_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
# On utilise le modèle le plus performant disponible
model = genai.GenerativeModel('gemini-2.5-flash') 

# --- FONCTIONS ---

def get_existing_tags():
    """
    Récupère la liste officielle des tags via la structure de la Data Source.
    (Plus besoin de scanner les pages une par une).
    """
    print("📚 Récupération des tags via l'API (Structure)...")
    try:
        # On récupère les infos de la Data Source directement
        ds_info = notion.data_sources.retrieve(data_source_id=DATABASE_ID)
        
        # On cherche la propriété "Tags"
        tags_prop = ds_info.get("properties", {}).get("Tags")
        
        if tags_prop and "multi_select" in tags_prop:
            options = tags_prop["multi_select"]["options"]
            tag_list = [opt["name"] for opt in options]
            print(f"   -> ✅ {len(tag_list)} tags officiels récupérés.")
            return ", ".join(tag_list)
            
    except Exception as e:
        print(f"⚠️ Erreur lors de la lecture de la structure : {e}")
        print("   (Assure-toi que l'ID dans .env est bien celui de la Data Source)")
    
    return ""

def get_pages_to_process():
    """Récupère les pages non traitées"""
    print(f"🔍 Recherche des recettes à traiter...")
    results = []
    query_filter = {"property": "IA Traitée", "checkbox": {"equals": False}}
    
    has_more = True
    start_cursor = None
    
    try:
        while has_more:
            # Utilisation de data_sources.query (API 2025)
            response = notion.data_sources.query(
                data_source_id=DATABASE_ID,
                filter=query_filter,
                start_cursor=start_cursor,
                page_size=10
            )
            results.extend(response["results"])
            has_more = response["has_more"]
            start_cursor = response["next_cursor"]
            
    except Exception as e:
        print(f"❌ Erreur scan pages : {e}")
            
    print(f"📋 {len(results)} recettes en attente.")
    return results

def get_page_text(page_id):
    """Lit le contenu de la page"""
    text_content = ""
    try:
        blocks = notion.blocks.children.list(block_id=page_id)
        for block in blocks['results']:
            type_block = block['type']
            if 'rich_text' in block[type_block]:
                for text_item in block[type_block]['rich_text']:
                    text_content += text_item['plain_text']
                text_content += "\n"
    except:
        pass
    return text_content

def ask_gemini(titre, texte_recette, existing_tags_str):
    """Prompt optimisé avec Tags officiels et Nettoyage Titre"""
    prompt = f"""
    Analyse cette recette.
    Titre actuel : {titre}
    Contenu : {texte_recette}
    
    Voici la liste EXACTE des tags existants dans la base : 
    [{existing_tags_str}]

    TACHE 1 : NETTOYAGE DU TITRE
    - Réécris le titre en minuscules (sauf 1ère lettre et Noms Propres).
    - Garde impérativement les émojis.
    - Ex: "TAJINE POULET 🍲" -> "Tajine poulet 🍲"
    
    TACHE 2 : EXTRACTION DONNÉES
    - "type": Choisis UN seul parmi : "Plat", "Entrée / Apéro", "Dessert & Douceurs", "Base / Sauce", "Boisson".
    - "tags": Choisis UNIQUEMENT parmi la liste des tags existants fournie ci-dessus. Si vraiment aucun ne correspond, tu peux en proposer un pertinent (ex: type de viande ou régime). PAS d'ingrédients simples (pas de "Courgette").
    - "temps_cuisson_repos": Additionne cuisson + repos + marinade.
    - "instructions": Synthétise les étapes claires et numérotées.

    Format JSON attendu :
    {{
        "clean_title": "Titre Propre",
        "type": "Plat",
        "tags": ["Tag1", "Tag2"],
        "temps_prepa": nombre (min) ou 0,
        "temps_cuisson_repos": nombre (min) ou 0,
        "nb_personnes": nombre ou 0,
        "ingredients": "liste complète...",
        "instructions": "1. Etape un...\\n2. Etape deux..."
    }}
    """
    
    try:
        response = model.generate_content(prompt)
        clean_json = re.sub(r"```json|```", "", response.text).strip()
        return json.loads(clean_json)
    except Exception as e:
        print(f"   [Erreur IA] {e}")
        return None

def update_notion_page(page_id, data, title_property_name):
    """Met à jour Notion"""
    props = {}
    
    # Renommage Titre
    if data.get("clean_title"):
        props[title_property_name] = {"title": [{"text": {"content": data["clean_title"]}}]}

    # Nombres
    if data.get("temps_prepa"): props["Temps de préparation (min)"] = {"number": data["temps_prepa"]}
    if data.get("temps_cuisson_repos"): props["Temps de cuisson (min)"] = {"number": data["temps_cuisson_repos"]}
    if data.get("nb_personnes"): props["Nombre de personnes"] = {"number": data["nb_personnes"]}
    
    # Tags & Type
    if data.get("tags"):
        props["Tags"] = {"multi_select": [{"name": t.capitalize()} for t in data["tags"][:6]]}
    if data.get("type"):
        props["Type"] = {"select": {"name": data["type"]}}
        
    # Textes Riches
    if data.get("ingredients"):
        ing_text = data["ingredients"]
        if isinstance(ing_text, list): ing_text = "\n".join(ing_text)
        props["Ingrédients"] = {"rich_text": [{"text": {"content": str(ing_text)[:2000]}}]}
        
    if data.get("instructions"):
        inst_text = data["instructions"]
        if isinstance(inst_text, list): inst_text = "\n".join(inst_text)
        props["Instructions"] = {"rich_text": [{"text": {"content": str(inst_text)[:2000]}}]}
    
    # Validation
    props["IA Traitée"] = {"checkbox": True}

    try:
        notion.pages.update(page_id=page_id, properties=props)
        return True
    except Exception as e:
        print(f"   [Erreur Update] {e}")
        return False

def main():
    print("🚀 IA Cuisinier v5 (API Structure 2025)")
    
    # 1. Récupération propre des tags
    existing_tags_str = get_existing_tags()
    
    # 2. Récupération des recettes
    pages = get_pages_to_process()
    
    if not pages:
        print("Rien à faire.")
        return

    count = 0
    for page in pages:
        page_id = page["id"]
        
        # Trouve le nom de la colonne Titre
        try:
            title_key = next((k for k, v in page["properties"].items() if v["type"] == "title"), "Nom")
            if page["properties"][title_key]["title"]:
                titre_actuel = page["properties"][title_key]["title"][0]["plain_text"]
            else:
                titre_actuel = "Sans titre"
        except:
            titre_actuel = "Inconnu"
            title_key = "Nom"
            
        print(f"\n🍳 {titre_actuel}")
        
        texte = get_page_text(page_id)
        if len(texte) < 20:
            print("   -> Page vide ? Je passe.")
            continue
            
        data = ask_gemini(titre_actuel, texte, existing_tags_str)
        
        if data:
            if update_notion_page(page_id, data, title_key):
                new_title = data.get('clean_title', titre_actuel)
                print(f"   -> ✅ OK (Renommé en : {new_title})")
                count += 1
            else:
                print("   -> ❌ Erreur écriture Notion")
        else:
            print("   -> ❌ Erreur réponse IA")
            
        time.sleep(1.5)
        
    print(f"\n✨ Fini : {count} recettes traitées.")

if __name__ == "__main__":
    main()