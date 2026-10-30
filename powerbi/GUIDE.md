# Rapport Power BI — guide de construction

Quatre pages qui répondent chacune à **une question** qu'un analyste de la Banque du Canada, d'une
banque ou d'un fonds se pose réellement, plus une page de santé du pipeline.

| Page | Question | Ce qui la rend différente |
|---|---|---|
| 1. Moniteur de décision | La Banque va-t-elle monter, maintenir ou baisser ? | Règle de Taylor **paramétrable**, ce que le marché anticipe, grille de signaux |
| 2. Choc pétrolier | Le choc de 2026 se propage-t-il au reste des prix ? | Pétrole **en dollars canadiens**, effet de change, **délai de transmission** mesuré |
| 3. Tarifs | Combien le Canada paie-t-il vraiment, et qui absorbe ? | Tarif **effectivement payé** vs concurrents, absorption par les exportateurs |
| 4. Renouvellement hypothécaire | Que paie un ménage qui renouvelle aujourd'hui ? | **Simulateur** de choc de paiement (paramètres what-if) |
| 5. Santé des données | Peut-on faire confiance aux chiffres ? | Fraîcheur, révisions, erreurs d'ingestion |

> Les tables `bi_*` sont aux **dates de référence** : l'IPC de septembre est affiché en septembre.
> La table `gold_model_table_monthly` (ML) est alignée sur les dates de publication — ne pas
> l'utiliser pour les graphiques.

---

## 1. Connexion aux données

### Option A — Databricks (recommandée)

1. Databricks → **SQL Warehouses** → ton entrepôt (Serverless Starter Warehouse) → **Connection details** :
   note `Server hostname` et `HTTP path`.
2. Databricks → avatar → **Settings → Developer → Access tokens → Generate new token** (90 jours).
3. Power BI Desktop → **Get data → Azure Databricks** (fonctionne aussi pour un espace AWS) →
   colle hostname et HTTP path → mode **Import** → authentification *Personal Access Token*.
4. Coche dans `workspace.cfl` :
   `bi_dim_date`, `bi_dim_series`, `bi_fact_observations`, `bi_fact_yield_curve`,
   `bi_fact_policy_decisions`, `bi_fact_policy_calendar`, `bi_mart_macro_monthly`,
   `bi_mart_energy_passthrough`, `bi_mart_policy_signals`, `freshness_report`, `bronze_ingestion_log`.

Mode **Import** (pas DirectQuery) : le modèle fait quelques Mo, et l'entrepôt gratuit n'a pas à
rester allumé pendant la navigation.

### Option B — fichiers locaux (sans Databricks)

```bash
uv run cfl run      # ou: uv run cfl bi
```

Power BI → **Get data → Parquet** → dossier
`\\wsl.localhost\Ubuntu\home\alouiyaz\canadian-financial-lakehouse\data\gold\bi\`.

---

## 2. Modèle (vue Modèle)

**Relations** (toutes *un-à-plusieurs*, filtre simple) :

| De (1) | Vers (*) |
|---|---|
| `bi_dim_date[date]` | `bi_mart_macro_monthly[month]` |
| `bi_dim_date[date]` | `bi_fact_yield_curve[date]` |
| `bi_dim_date[date]` | `bi_fact_observations[date]` |
| `bi_dim_date[date]` | `bi_fact_policy_decisions[announcement_date]` |
| `bi_dim_series[name]` | `bi_fact_observations[name]` |

Puis :
- `bi_dim_date` → **Mark as date table** (colonne `date`).
- `bi_fact_yield_curve[tenor]` → **Sort by column** `tenor_months` (sinon 10Y passe avant 1M).
- `bi_dim_date[month_name]` → trier par `month_number`.
- Masquer les colonnes techniques (`source_id`, `cycle_id`, `*_threshold`…).
- Formats : taux en `0.00`, points de base en `0`, dollars en `$#,0`.

**Paramètres what-if** (Modeling → New parameter → Numeric range) — voir l'en-tête de
[`measures.dax`](measures.dax). **Mesures** : créer une table `_Measures` et y coller
[`measures.dax`](measures.dax), en respectant les dossiers d'affichage indiqués.

**Thème** : View → Themes → Browse for themes → [`cfl-theme.json`](cfl-theme.json).

---

## 3. Les pages

Format 16:9, fond beige du thème, un titre qui **affirme** la conclusion (pas « Inflation » mais
« L'inflation fondamentale est sous la cible malgré le choc pétrolier »).

### Page 1 — Moniteur de décision

```
┌────────────┬────────────┬────────────┬──────────────────────────────┐
│ Taux       │ Dernière   │ Prochaine  │  Posture nette : Hawkish bias │
│ directeur  │ décision   │ décision   │  ▲ 4 signaux  ▼ 1 signal      │
│ 2.50 %     │ +25 bp …   │ J-40       │                               │
├────────────┴────────────┴────────────┼──────────────────────────────┤
│ Taux directeur vs règle de Taylor    │ Grille de signaux             │
│ (courbes + zone d'écart)             │ indicateur | valeur | signal  │
│ curseurs : r*, poids inflation,      │ (couleur = [Signal Color])    │
│ poids chômage                        │                               │
├──────────────────────────────────────┼──────────────────────────────┤
│ Inflation vs cible : bande 1–3 %,    │ Ce que le marché anticipe     │
│ totale + 3 mesures fondamentales     │ [Market-Implied Move 6M (bp)] │
└──────────────────────────────────────┴──────────────────────────────┘
```

- **Cartes** : `[Policy Rate (latest)]`, `[Last Decision]`, `[Days to Next Decision]`, `[Net Policy Stance Label]`.
- **Courbes** : axe `bi_mart_macro_monthly[month]`, valeurs `[Policy Rate]`, `[Taylor Rule Rate]` ;
  **3 segments** (slicers) sur les paramètres *Neutral real rate*, *Inflation weight*, *Slack weight*.
  Sous le graphique, une carte `[Taylor Reading]`.
- **Inflation vs cible** : courbes `[Headline CPI (y/y)]`, `[CPI-trim]`, `[CPI-median]`, `[CPI-common]` +
  lignes constantes `[Target Band Low]`, `[Target]`, `[Target Band High]` (Analytics → constant line).
- **Grille** : tableau sur `bi_mart_policy_signals` (indicator, latest_value, unit, signal_label),
  arrière-plan conditionnel de `signal_label` = `[Signal Color]`, info-bulle = `rationale`.
- **Décisions** : ajoute `bi_fact_policy_decisions` en points sur la courbe du taux (marqueurs).
  `announcement_date` = jour de l'annonce ; `date` = entrée en vigueur (jour ouvrable suivant).

### Page 2 — Choc pétrolier et inflation

- Courbe double axe : `[WTI (USD)]` et `[WTI (CAD)]` ; carte `[FX Effect on Oil (pts)]` (le dollar
  canadien a-t-il amorti ou amplifié le choc ?).
- Colonnes empilées : `[Core Inflation (avg)]` + `[Headline minus Core (pts)]` = inflation totale :
  la partie « énergie » se voit d'un coup d'œil.
- **Graphique des délais** : colonnes `bi_mart_energy_passthrough[lag_months]` × `corr_core` (et
  `corr_headline` en ligne) ; carte `[Pass-through Reading]`. C'est la vue qu'on ne trouve nulle part.
- Segment de période (2021–2023 vs 2025–2026) pour comparer les deux chocs.

### Page 3 — Tarifs : annoncé ou payé ?

- Courbes `[US Tariff on Canada (%)]`, `[US Tariff on Mexico (%)]`, `[US Tariff on China (%)]` depuis 2024.
- Carte `[Canada Advantage vs China (pts)]` et `[Tariff Change vs Pre-2025 (pts)]`.
- Colonnes `[US Import Prices from Canada (y/y %)]` + carte `[Exporter Absorption Reading]`.
- Aire `[Trade Policy Uncertainty]` avec `[USD/CAD]` en ligne (axe secondaire).
- Note de bas de page : *Les tarifs annoncés (25–35 %) ne s'appliquent pas aux biens conformes à
  l'ACEUM ; le taux effectif = droits perçus / valeur importée (US Census).*

### Page 4 — Choc de renouvellement hypothécaire

```
┌─────────────────────┬──────────────────────────────────────────────┐
│ Montant  [500 000]  │  Mensualité à l'origine   2 441 $            │
│ Amortissement [25]  │  Mensualité au renouvellement  3 106 $        │
│ Mois (segment)      │  Choc : +665 $/mois  (+27 %)  ·  +7 980 $/an  │
├─────────────────────┴──────────────────────────────────────────────┤
│ Taux 5 ans aujourd'hui vs taux 5 ans il y a 5 ans (courbes)         │
├──────────────────────────────────────────────────────────────────────┤
│ Marge bancaire : taux hypothécaire 5 ans − obligation 5 ans          │
└──────────────────────────────────────────────────────────────────────┘
```

- Segments sur *Mortgage amount* et *Amortization years* ; segment de mois (`bi_mart_macro_monthly[month]`,
  sélection unique) pour voir le choc d'une cohorte donnée.
- Cartes : `[Payment at Origination]`, `[Payment at Renewal]`, `[Monthly Payment Shock ($)]`,
  `[Monthly Payment Shock (%)]`, `[Annual Payment Shock ($)]`.
- Note : *taux affichés (posted) des banques — les taux négociés sont plus bas ; le choc relatif reste
  représentatif.*

### Page 5 — Santé des données (bonus)

- Cartes `[Data Freshness Score]`, `[Series Late or Missing]`, `[Ingestion Errors]`.
- Tableau `freshness_report` (name, source, last_date, age_days, max_age_days, status) coloré par statut.
- Colonnes `bronze_ingestion_log` : séries modifiées par run (`[Series Changed (runs)]` par `ingested_at`).

### Courbe des taux (dans la page 1 ou une page 6)

Courbe axe `bi_fact_yield_curve[tenor]`, valeurs `[Yield on Selected Date]` et `[Yield 1 Year Earlier]`,
segment de date unique ; carte `[Curve Inverted]`.

---

## 4. Pour le portfolio

1. **Enregistre en projet Power BI** : File → Save as → *Power BI project (.pbip)*. Le rapport devient
   des fichiers texte (modèle TMDL + pages JSON) versionnés dans `powerbi/` : un recruteur voit le
   modèle et les mesures directement sur GitHub. Garde aussi le `.pbix` pour l'ouvrir en un clic.
2. Captures de chaque page dans `docs/img/powerbi_*.png` + un GIF de 20 s du simulateur hypothécaire
   et des curseurs de Taylor pour le README.
3. Ajoute un texte alternatif à chaque visuel (accessibilité, très apprécié dans le secteur public).
