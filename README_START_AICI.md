# PROTECMed — începeți aici

**Versiunea 2 · 5 septembrie 2026 · pachet de documentație și referințe, nu aplicație instalabilă.**

Prototipul numără cohorte local, criptează numărul fiecărui furnizor și adună ciphertext-urile cu OpenFHE. Rezultatul se obține prin contribuția tuturor celor 2 sau 3 furnizori. Nu se implementează Kaplan–Meier sau alte statistici în această etapă.

## Ordinea de lucru

1. Citiți `CHANGELOG.md`, apoi secțiunile 1–4 din `IMPLEMENTATION_BLUEPRINT.md`.
2. Puneți `AGENTS.md` la rădăcina repository-ului de implementare și utilizați câte un task din secțiunea 7.
3. Rulați testele Python pe date sintetice. Verificați `verification/verification.json` pentru limitele verificării.
4. Începeți M0: compilarea OpenFHE și a exemplului C++. M2 separă procesele și cheile; M3 adaugă protocolul semnat. Abia apoi implementați interfața și instalarea IOCN.

## Fișiere principale

| Fișier/director | Utilizare |
|---|---|
| `IMPLEMENTATION_BLUEPRINT.md` și Word-ul echivalent | Specificația completă, în engleză |
| `docs/` | Aceleași capitole separat, pentru task-uri și agenți |
| `config/` | Parametri, mapping, catalog Q001–Q006 și rezultate agregate IOCN |
| `contracts/` | Scheme JSON și regulile de validare semantică |
| `reference/python/` | Referințe executabile pentru numărări, semnături și audit local |
| `reference/cpp/` | Exemplu OpenFHE și CMake; încă necompilate în acest mediu |
| `fixtures/`, `tests/` | Date independente sintetice și teste |
| `templates/`, `verification/` | Task-uri, acceptanță, benchmark și verificări efectuate |
| `assets/` | Diagrama de arhitectură și sursele editabile |

## Comenzi care funcționează pentru referințele incluse

Rulați la rădăcina pachetului, într-un mediu Python separat:

```bash
python -m pip install -r reference/python/requirements-reference.txt
python -m unittest discover -s tests -v
python reference/python/cohort.py fixtures/synthetic_cohorts.csv --catalogue config/query-catalog.json
```

Instalarea dependențelor necesită acces la un index aprobat sau un cache local. Testele au fost executate cu dependențele deja instalate, nu ca probă a unei instalări offline.

## Limite importante

Testele Python nu validează OpenFHE sau serviciile web. Exemplul C++ trebuie compilat și rulat în M0. În pachet nu există imagini Docker, servicii FastAPI finalizate sau instalatoare Windows/Mac. Acestea sunt livrabile ale programatorului, descrise exact în document.

Fișierul IOCN și rândurile pacienților NU sunt incluse. Rezultatele agregate din `config/iocn_expected_counts.json` și anexa clinică sunt informații de cercetare cu acces restricționat; eliminați-le înaintea publicării unui repository. Datele reale nu se introduc în prompturi AI, CI public sau build-uri Docker.

Pentru Q004, rezultatul plaintext verificat este 11: 5+6 sau 3+2+6. Coloana WBC conține formule; folosiți numai valori salvate revizuite local sau un export values-only verificat. Un rezultat salvat nu dovedește automat prospețimea formulei.

În configurația 2/2, totalul și un count local permit deducerea celuilalt count. După emiterea unei decriptări parțiale, aceasta nu poate fi retrasă criptografic. Aceste limite trebuie explicate operatorilor, nu ascunse în interfață.
