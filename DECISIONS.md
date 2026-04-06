# DecRAS — Decision Log

> Append-only log of architectural decisions made in claude.ai conversations.
> Claude Code reads this file for context. Do not edit manually except to append.

---

## 2026-03-29 — IK Bypass: Joint-Space Lookup Table

**Decision**: Replace placo/PyBullet IK with data-driven joint-space lookup table built from teleoperation recordings.

**Reason**: placo IK uses DH parameters that don't match the actual 3D-printed SO-101 arm geometry. The arm moves to wrong positions. This is fundamental — no amount of tuning fixes incorrect DH parameters on a 3D-printed arm.

**Approach**: Teleoperate arm to ~75 positions across workspace, record (Cartesian_position, joint_angles) pairs, use KDTree + inverse-distance interpolation for arbitrary targets. All trajectory generation in joint space via minimum-jerk profiles.

**Impact**:
- New Phase 5.5 inserted before Phase 6 (BACKLOG.md)
- Phase 6 (imitation learning) blocked until motion control is reliable
- New Decision #6 added to ARCHITECTURE.md
- Files to build: calibration/record_grid.py, control/joint_lookup.py, control/trajectory.py, control/executor.py

---

## 2026-03-29 — Project Workflow Established

**Decision**: Three-doc system (ARCHITECTURE.md + BACKLOG.md + DECISIONS.md) with automated sync.

**Reason**: Architectural decisions made in claude.ai conversations were not flowing into the repo. Claude Code had no visibility into strategic direction discussed here.

**Workflow**:
- End of each claude.ai conversation → Claude produces a sync block → user appends to DECISIONS.md
- Claude Code reads DECISIONS.md before every task (per CLAUDE.md rules)
- Every PR updates BACKLOG.md (check off task) + PROJECT_STATUS.md (new capabilities)
- Daily pulse via scripts/daily_pulse.py (GitHub Actions when billing unlocked)

---

Stratégie Compétences & Positionnement — Avril 2026
Constat de départ
Profil actuel : AI Engineer en poste (vision, LLM, RAG, Graph RAG, MCP servers, embeddings)
Problème : ce profil se commoditise rapidement. L'AI Engineer généraliste de 2024 sera le web dev de 2026.
Objectif : anticiper à 2 ans, trouver un positionnement différenciant.
Hypothèse initiale
Se spécialiser en IA embodied/embedded (ex : streaming JEPA sur mobile).
Analyse
Ce qui se commoditise vite
Intégration LLM, RAG, prompt engineering, fine-tuning standard
Orchestration d'agents basique
Les outils comme Claude Code rendent ça accessible aux non-spécialistes
Ce qui reste dur à commoditiser
Compétences qui touchent au physique : latence real-time, bruit capteur, sécurité, edge cases physiques
Maths et théorie derrière les architectures : Koopman, JEPA, contrôle différentiable — concevoir les outils, pas les utiliser
Pensée système sur problèmes ambigus : savoir quoi construire, pas juste comment
Marché belge
Demande réelle en robotique/embedded : ART Robotics (Herent), Mantis Robotics (Leuven), IMEC, Space Applications Services, Toyota Zaventem
UHasselt recrute en "cyber-physical intelligence" (embedded/edge AI, contrôle sécurisé, HW-SW co-design)
Écosystème plus petit que le pur software mais moins saturé
Positionnement retenu
"AI × Systèmes Cyber-Physiques" — le profil qui sait déployer de l'intelligence (world models, perception, planification) sur des systèmes contraints interagissant avec le monde réel.
Différenciateur clé vs ingénieur embedded classique : compréhension des world models, architectures JEPA, alignment latent. La combinaison embedded + ML théorique est rare.
Compétences à empiler
Immédiat (0-6 mois)
Finaliser le POC DecRAS en Python (architecture + interfaces validées)
Bases C++ suffisantes pour ne pas être bloqué sur opportunités
ONNX Runtime / TFLite pour inférence edge
ROS2 (bases déjà acquises)
Moyen terme (6-18 mois)
Rust comme langage cible post-POC (refactor bloc par bloc)
Écosystème ML Rust : burn, ort (ONNX), candle (HuggingFace)
Bindings ROS2 Rust (r2r, ros2_rust)
En attendant le refactor : petits outils CLI perso en Rust pour construire le muscle
Contrôle en boucle fermée (atout existant via travail Koopman)
Safety/certification (ISO 26262, IEC 61508) — rend le profil rare
MLOps pour systèmes embarqués (monitoring de drift sur edge)
Séquence décidée
POC Python d'abord — valider l'architecture et les blocs DecRAS
Refactor Rust ensuite — bloc par bloc, une fois les interfaces stabilisées
Ne pas optimiser prématurément
DecRAS comme vitrine
Cadrer le projet non pas comme "hobby robotique" mais comme démonstration de compétences systèmes :
"Architecte d'un système multi-agents avec planification LLM, perception temps réel et contrôle de bras robotique sous contraintes edge"
Pari Rust — risques et timing
Pour : profil Rust + IA embarquée quasi inexistant, avance sur une vague
Contre : le marché belge recrute en C++ aujourd'hui, Rust robotique encore marginal
Mitigation : passer de Rust à C++ est facile, l'inverse non
Horizon : pari à 2-3 ans, pas 6 mois
Discussion du 2 avril 2026

---


We need to take a step back and update the plans and decisions. The idea is to make a very simple simple stuff first.
1. Code by hand the SO-101 class
2. Find the URDF of SO-101
3. Put it into Mujoco
4. Visualize where is the origin.
5. Fix FK
6. Verify IK(FK) = ID (approx)
7. Valider les différentes directions cartesiennes.

---

