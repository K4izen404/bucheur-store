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

### Wave (actif) — flux manuel simplifié

Aucun compte Wave Business / KYC requis : le marchand utilise son lien Wave personnel
(modifiable dans Admin → Réglages → « Lien Wave »).

1. Le client commande → page paiement avec le montant exact et le lien Wave du marchand.
2. Il paie via son application Wave et **colle la référence de transaction** (ex : TCN4Y4ZC3FM).
3. L'admin reçoit un email « Paiement à vérifier » avec la référence, **vérifie sur son compte Wave**
   puis valide dans l'administration (Commandes → statut paiement = Payé). Le client est
   notifié par email automatiquement.

### Intégration automatique (optionnelle, prête)

Le code d'une intégration API officielle (session serveur + webhook HMAC) existe dans
`wave_pay/` (microservice FastAPI + service systemd `bucheur-wave`). Pour l'activer, il faut
un **compte Wave Business** (business.wave.com, validation KYC 3-7 jours), puis :
- remplir `WAVE_API_KEY`, `WAVE_WEBHOOK_SECRET` dans `bucheur-wave.service` et
  `systemctl --user enable --now bucheur-wave.service` ;
- ajouter `WAVE_SERVICE_URL`/`WAVE_INTERNAL_SECRET` à `bucheur-store.service` et rétablir
  l'appel au service dans `checkout()` (voir commit `763c582`) ;
- un domaine **HTTPS** pour l'URL du webhook.

**Orange Money (en cours)** : masqué du tunnel tant que le compte Marchand n'est pas actif. À activer dans Admin → Réglages (`om_status = active`).

## Production

- Changer `app.secret_key` (variable d'environnement `SECRET_KEY`)
- Utiliser un serveur WSGI (gunicorn/waitress) au lieu du serveur de dev
- HTTPS + hébergement (Vercel/Render/Hostinger selon le budget) + nom de domaine

### PythonAnywhere (gratuit)

Guide complet : `DEPLOIEMENT_PYTHONANYWHERE.md` (à la racine du projet).