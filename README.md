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
- **Comptes vérifiés** : inscription par **email uniquement** (le téléphone est un simple contact, pas un identifiant), validation par code OTP à 6 chiffres (10 min de validité) avant la première connexion. L'email est obligatoire et unique en base.
- **Panier & commande réservés aux comptes connectés et vérifiés** : sans compte vérifié, l'ajout au panier invite à se connecter (retour automatique après connexion).
- **Brute force** : verrouillage 10 min après 5 échecs de connexion (client et admin).
- **Upload** : extensions filtrées + vérification du contenu réel de l'image (Pillow).
- **En-têtes HTTP** : X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy, Content-Security-Policy.
- **Mots de passe** : hachés (werkzeug), jamais en clair.
- **Injection SQL / XSS** : requêtes paramétrées + échappement automatique Jinja2.

Variables d'environnement utiles : `SECRET_KEY`, `ADMIN_PASSWORD` (seed), `FORCE_HTTPS=1` (cookie Secure + HSTS).
**SMTP obligatoire pour l'inscription** : `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (ex. Gmail). Sans SMTP configuré, l'inscription affiche un message d'indisponibilité. Mode développement uniquement (jamais actif par défaut) : `FLASK_ENV=development` sans SMTP affiche le code OTP sur la page.

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
- Catalogue avec filtres (modèle, couleur, stockage, état, repliables sur mobile) + recherche + tri
- Panier en session (ajout AJAX sans rechargement, badge mis à jour), tunnel de commande en 3 étapes
- Téléphone du client obligatoire et vérifié au moment de la commande (pré-rempli depuis le compte), cliquable (appel/WhatsApp) côté admin
- Paiement Wave (session officielle créée côté serveur, webhook sécurisé HMAC, confirmation automatique), Orange Money (désactivable, « bientôt »), à la livraison
- Comptes clients : inscription par email + vérification OTP, connexion, historique des commandes
- Contact : WhatsApp +221 77 757 27 76 (bouton flottant), livraison à Rufisque & Nord-Foire
- Design premium sombre + animations, toasts de notification, validation des formulaires côté client, accessibilité (zones tactiles ≥ 44 px)

**Admin**
- Tableau de bord : CA total/jour/semaine, répartition Wave/OM, graphique 7 jours, meilleures ventes
- Gestion produits : ajout/modif/suppression, image, stock, vedette, promo
- Commandes : liste filtrée, détail, changement de statut commande + paiement
- Utilisateurs : liste (commandes, total dépensé), ajout/modif/suppression, droits admin, réinitialisation de mot de passe, suppression protégée (dernier admin / self)
- Réglages : lien Wave et statut Orange Money modifiables, changement de mot de passe

## Paiements

### Wave (actif) — intégration API officielle

1. Le montant est **lu en base** au moment du checkout (jamais fourni par le navigateur).
2. Un **microservice FastAPI** (`wave_pay/`, port 5001, service systemd `bucheur-wave`) crée la session
   `POST https://api.wave.com/v1/checkout/sessions` (devise XOF, `restrict_payer_mobile`) et redirige
   l'acheteur vers `wave_launch_url`.
3. Wave notifie le **webhook** `POST /webhook/wave` avec un header `Wave-Signature` (HMAC-SHA256 sur
   `timestamp + corps brut`). La signature est vérifiée (anti-rejeu 5 min).
4. Si l'événement `checkout.session.completed` correspond à un `client_reference` `order-<id>`, le service
   appelle la route interne Flask `POST /api/paiement/confirme/<id>` (secret partagé
   `X-Internal-Secret`) qui **re-vérifie le montant contre la base** (refus 422 si incohérent) puis passe
   la commande en **PAYÉE** et notifie client + admin par email. Idempotent.
5. Aucune confirmation n'est jamais acceptée côté client.

**Identifiants requis** (variables d'environnement de `bucheur-wave.service`) :
- `WAVE_API_KEY` : clé API du portefeuille (developer.wave.com → Business Portal → Applications).
  Production `wave_sn_prod_...`, sandbox `wave_sn_test_...`.
- `WAVE_WEBHOOK_SECRET` : secret de signature des webhooks (fourni à l'enregistrement du webhook
  dans le Business Portal).
- `WAVE_API_BASE` : `https://api.wave.com` (prod) ou `https://api.wave.com/v1/sandbox` (test).
- `WAVE_SIGNING_SECRET` : secret de signature des *requêtes* API (optionnel).
- `WAVE_INTERNAL_SECRET` : secret partagé avec Flask (même valeur dans `bucheur-store.service`).
- `WAVE_SUCCESS_URL_BASE` : base du site pour `success_url`/`error_url` (**HTTPS exigé par Wave**).
- `FLASK_INTERNAL_URL` : URL interne de Flask (garder `http://127.0.0.1:5000`).

**Orange Money (en cours)** : masqué du tunnel tant que le compte Marchand n'est pas actif. À activer dans Admin → Réglages (`om_status = active`).

## Production

- Changer `app.secret_key` (variable d'environnement `SECRET_KEY`)
- Utiliser un serveur WSGI (gunicorn/waitress) au lieu du serveur de dev
- HTTPS + hébergement (Vercel/Render/Hostinger selon le budget) + nom de domaine