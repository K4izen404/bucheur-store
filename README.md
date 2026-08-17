# Bûcheur Store — Site e-commerce

Site web e-commerce de vente d'iPhones, avec interface **Client** et interface **Admin**, paiement **Wave** (actif) et **Orange Money** (en cours), en Python + Flask + SQLite.

## Démarrage

```bash
cd bucheur_store
../venv/bin/python app.py   # ou : python app.py
```

Le site tourne sur http://127.0.0.1:5000

- **Site client** : http://127.0.0.1:5000/
- **Espace Admin** : http://127.0.0.1:5000/admin/login

## Compte administrateur (démo)

| Email | Mot de passe |
|---|---|
| admin@bucheur.sn | bucheur2026 |

⚠️ À changer avant mise en production (réglages → ou directement dans la base).

## Structure

```
bucheur_store/
├── app.py              # Routes Flask (client + admin)
├── db.py               # Schéma SQLite + helpers
├── bucheur.db          # Base de données (créée au 1er lancement)
├── static/
│   ├── css/            # style.css (client) + admin.css
│   ├── js/main.js      # Animations (reveal, panier, etc.)
│   └── uploads/        # Logo + images produits
└── templates/
    ├── base.html, index.html, catalog.html, product.html,
    │   cart.html, checkout.html, payment.html, order_success.html,
    │   account.html, _product_card.html
    ├── auth/           # login.html, register.html
    └── admin/          # login, dashboard, products, orders, customers, settings
```

## Fonctionnalités

**Client**
- Catalogue avec filtres (modèle, couleur, stockage, état) + recherche + tri
- Panier en session, tunnel de commande
- Paiement Wave (redirection vers le lien officiel + saisie de la référence), Orange Money (désactivable, « bientôt »), à la livraison
- Comptes clients : inscription, connexion, historique des commandes
- Design premium sombre + animations (reveal au scroll, hover cards, badge panier animé, checkmark animé)

**Admin**
- Tableau de bord : CA total/jour/semaine, répartition Wave/OM, graphique 7 jours, meilleures ventes
- Gestion produits : ajout/modif/suppression, image, stock, vedette, promo
- Commandes : liste filtrée, détail, changement de statut commande + paiement
- Clients : liste avec total dépensé
- Réglages : lien Wave et statut Orange Money modifiables

## Paiements

- **Wave (actif)** : lien `https://pay.wave.com/m/M_-ufM0UEnXp2n/c/sn/` — redirection, puis le client saisit sa référence. L'admin valide la commande.
- **Orange Money (en cours)** : masqué du tunnel tant que le compte Marchand n'est pas actif. À activer dans Admin → Réglages (`om_status = active`).

## Production

- Changer `app.secret_key` (variable d'environnement `SECRET_KEY`)
- Utiliser un serveur WSGI (gunicorn/waitress) au lieu du serveur de dev
- HTTPS + hébergement (Vercel/Render/Hostinger selon le budget) + nom de domaine