# Bûcheur Études & Business — Site e-commerce

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

⚠️ **Changez ce mot de passe dès la mise en ligne** : Admin → Réglages → « Changer mon mot de passe ».

## Sécurité

- **Secret key** : générée aléatoirement au premier lancement (stockée en base). Surchargée par la variable d'environnement `SECRET_KEY`.
- **CSRF** : jeton requis sur tous les formulaires (POST) — refusés sans jeton valide.
- **IDOR** : les pages de commande/paiement ne sont accessibles qu'au client concerné (session ou compte connecté).
- **Comptes vérifiés** : inscription par email OU téléphone, validation par code OTP à 6 chiffres (10 min de validité) avant la première connexion.
- **Brute force** : verrouillage 10 min après 5 échecs de connexion (client et admin).
- **Upload** : extensions filtrées + vérification du contenu réel de l'image (Pillow).
- **En-têtes HTTP** : X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, Content-Security-Policy.
- **Mots de passe** : hachés (werkzeug), jamais en clair.
- **Injection SQL / XSS** : requêtes paramétrées + échappement automatique Jinja2.

Variables d'environnement utiles : `SECRET_KEY`, `ADMIN_PASSWORD` (seed), `FORCE_HTTPS=1` (cookie Secure + HSTS).
Envoyer les codes OTP par email : `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (ex. Gmail). Sans SMTP configuré, le code s'affiche sur la page en mode développement.

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
    ├── auth/           # login.html, register.html, otp.html
    └── admin/          # login, dashboard, products, orders, users, settings
```

## Fonctionnalités

**Client**
- Catalogue avec filtres (modèle, couleur, stockage, état) + recherche + tri
- Panier en session, tunnel de commande
- Paiement Wave (redirection vers le lien officiel + saisie de la référence), Orange Money (désactivable, « bientôt »), à la livraison
- Comptes clients : inscription (email ou téléphone) + vérification OTP, connexion, historique des commandes
- Contact : WhatsApp +221 77 757 27 76 (bouton flottant), livraison à Rufisque & Nord-Foire
- Design premium sombre + animations (reveal au scroll, hover cards, badge panier animé, checkmark animé)

**Admin**
- Tableau de bord : CA total/jour/semaine, répartition Wave/OM, graphique 7 jours, meilleures ventes
- Gestion produits : ajout/modif/suppression, image, stock, vedette, promo
- Commandes : liste filtrée, détail, changement de statut commande + paiement
- Utilisateurs : liste (commandes, total dépensé), ajout/modif/suppression, droits admin, réinitialisation de mot de passe, suppression protégée (dernier admin / self)
- Réglages : lien Wave et statut Orange Money modifiables, changement de mot de passe

## Paiements

- **Wave (actif)** : lien `https://pay.wave.com/m/M_-ufM0UEnXp2n/c/sn/` — redirection, puis le client saisit sa référence. L'admin valide la commande.
- **Orange Money (en cours)** : masqué du tunnel tant que le compte Marchand n'est pas actif. À activer dans Admin → Réglages (`om_status = active`).

## Production

- Changer `app.secret_key` (variable d'environnement `SECRET_KEY`)
- Utiliser un serveur WSGI (gunicorn/waitress) au lieu du serveur de dev
- HTTPS + hébergement (Vercel/Render/Hostinger selon le budget) + nom de domaine