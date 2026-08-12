# BB_MeanReversion_Signal — Indicateur MT4

Indicateur MetaTrader 4 (pas de trading automatique) basé sur une stratégie
Bollinger Bands mean-reversion : période **15**, déviation **2,5σ**, retour
à la moyenne visé à **0,3σ**. Il scanne jusqu'à **20 paires** en tâche de
fond et t'alerte (popup MT4 + Telegram + notification push optionnelle) dès
qu'un signal apparaît. **Aucun ordre n'est jamais envoyé** — les SL/TP/lot
affichés dans l'alerte sont de simples suggestions calculées pour info.

⚠️ Ce script est un outil, pas un conseil en investissement. Les paramètres
viennent d'un backtest sur GBP/USD H4 2020-2022 uniquement (données
historiques, coûts simplifiés) — leur pertinence sur les 19 autres paires
n'a pas été validée individuellement.

## Installation

1. Dans MT4 : `Fichier` → `Ouvrir le dossier de données`.
2. Copie `BB_MeanReversion_Signal.mq4` dans `MQL4/Indicators/`.
3. Redémarre MT4, ou clic droit sur `Indicateurs personnalisés` dans le
   Navigateur → `Actualiser`.
4. Compile-le dans MetaEditor (F4 puis F7) et vérifie qu'il n'y a pas d'erreur.
5. Glisse-le sur n'importe quel
