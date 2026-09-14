---
title: "PROTECMed"
subtitle: "Pachetul pentru programatori — versiunea revizuită"
date: "5 septembrie 2026 · versiunea 2.0"
lang: ro-RO
---

Am refăcut documentația de implementare pentru prototipul de numărare a cohortelor, păstrând scenariile **2 din 2** și **3 din 3**. Pachetul include documentul Word detaliat, versiunea Markdown, documentația modulară pentru repository și referințe executabile de test. Nu include Kaplan–Meier, regresie sau alte analize statistice.

# Ce se implementează

Fiecare furnizor selectează și validează local fișierul de date, aplică aceeași definiție de cohortă și criptează count-ul local sub cheia publică generată în comun. Coordonatorul primește ciphertext-urile, execută `EvalAdd` și solicită aprobarea rezultatului. Fiecare furnizor verifică intrările și suma criptată înainte de a aproba local și de a produce decriptarea sa parțială. Rezultatul este obținut după contribuția tuturor furnizorilor.

Această versiune demonstrează filtrare federată și agregare homomorfă; nu pretinde că filtrarea rândurilor se face la server pe coloane criptate. Extensia pentru indicatori criptați este separată și nu condiționează prototipul inițial.

# Corecturile esențiale

**Parametrii OpenFHE.** Profilul fixează explicit `SetThresholdNumOfParties(n)`. Numărul participanților din interfață nu setează automat acest parametru. Păstrăm OpenFHE v1.5.1, BGV și modul `NOISE_FLOODING_MULTIPARTY`, cu dimensionare automată la nivelul de securitate specificat. Trimiterile către sursele oficiale sunt în capitolul 11 al blueprint-ului.

**Acordul pentru decriptare.** `MultipartyDecryptFusion` nu verifică singur identitatea instituțiilor sau acordul lor. Aplicația trebuie să verifice exact cei doi sau trei semnatari, rolurile lead/main, același rezultat și aceeași cerere. Nu este suficientă semnarea unui hash opac: fiecare agent verifică toate contribuțiile semnate și recalculează suma criptată înainte de aprobarea locală.

**Datele IOCN.** Toate cele 51 de celule din coloana WBC selectată conțin formule. Importul trebuie să folosească valori salvate revizuite local sau un export values-only verificat; un cache lipsă ori eronat blochează importul. Fișierul are și o referință externă, care nu trebuie actualizată de prototip. Verificarea efectuată aici nu stabilește prospețimea formulelor.

**Numărătorile de control.** Cele șase totaluri rămân 51, 29, 13, 11, 21 și 9. Pentru Q004, rezultatul este **11**, cu împărțirea **5 + 6** sau **3 + 2 + 6**. Acestea sunt rezultate de regresie pe date în clar, nu benchmarkuri OpenFHE. Nu au fost incluse rânduri de pacienți în pachet.

**Limitele de securitate.** În 2/2, totalul și count-ul propriu permit deducerea count-ului celuilalt furnizor. O decriptare parțială deja transmisă nu poate fi retrasă criptografic. Aceste limite sunt explicate explicit. Cheile rămân în stocare temporară locală: o deconectare de rețea nu este același lucru cu repornirea containerului și pierderea cheii.

# Ce primește programatorul

Documentul principal descrie arhitectura, protocolul, mapping-ul, schemele JSON, comenzile CLI de implementat, API-urile, interfața minimă și instalarea. Arhiva include `README_START_AICI.md`, `AGENTS.md`, un registru al schimbărilor, configurații, scheme JSON, date sintetice independente, referințe Python, exemplul C++/CMake, un model Compose și șabloane de task-uri, teste și acceptanță.

Cele 57 de teste executate verifică numai logica de referință Python, validarea schemelor, semnăturile și cazuri sintetice de cache Excel. Exemplul C++ a fost verificat față de API-urile publicate, dar **nu a fost compilat sau executat în acest mediu**. Nu au fost testate aici serviciile web, imaginile Docker, instalarea Windows/macOS sau un pilot clinic. `verification/verification.json` păstrează această distincție.

# Cum începe implementarea

Programatorul citește `README_START_AICI.md`, apoi capitolele 1–4 și `AGENTS.md`. Rulează testele Python pe fixture-ul sintetic și începe **M0: compilarea și rularea reală a OpenFHE**. Urmează separarea proceselor și serializarea în M2, protocolul semnat în M3 și abia apoi interfața web și instalarea IOCN.

Interfața propusă este simplă: import/validare, starea studiului și ecranul local de aprobare. Pentru validare distribuită se folosesc calculatoare distincte; trei containere pe același laptop reprezintă o simulare. Documentația și exemplul într-un singur proces nu certifică singure TRL 4/5: maturitatea trebuie susținută prin implementarea integrată, teste și acceptanța într-un mediu relevant.
