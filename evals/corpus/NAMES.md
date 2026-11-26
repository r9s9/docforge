# Invented names in the corpus

Every company and person in the corpus is invented. No employer, client or third-party material
is used anywhere (brief §9).

## Companies

Each company name got one exact-phrase web search on **2026-11-26**, before it was used. **None
of them matched a company.** The table lists the closest names the search returned. They are
different names, noted so a later check can compare.

| Name | Used as | Closest search results (not matches) |
|---|---|---|
| Tellmoor Data Services Ltd | English supplier, invoice issuer, NDA party A | Telmore (Danish mobile operator), Tellmo Byggplåt AB |
| Brisenthal Softwarehaus GmbH | German supplier, invoice issuer, NDA party A | Brisay Bugelmaschinenbau GmbH |
| Quorvane Logistics Ltd | English customer / party B | QuVa Pharma, Quorum Innovations |
| Pellbrook Marine Supplies Ltd | English customer / party B | Philbrook's Boatyard, Brook Marine Ltd |
| Ostrevik Engineering Ltd | English customer / party B | Brevik Engineering, Trosvik |
| Calvenna Health Partners Ltd | English customer / party B | Calcium (HealthChampion), Cala Health |
| Merrowind Retail Group Ltd | English customer / party B | Morrowind (a video game), no company |
| Thistlecombe Energy Ltd | English customer / party B | Thistle Energy Consulting Ltd, Thistle Energy Supply Ltd |
| Varnholt Publishing Ltd | English customer / party B | Holt Publishing Ltd, Varnham & Sons Holding ApS |
| Glenmarrow Facilities Ltd | English customer / party B | Glenmhor Facilities Management Ltd, Glenbarrow Construction Ltd |
| Kesselwind Logistik GmbH | German customer / Partei B | KESSLER energy GmbH, bewind GmbH |
| Auerbrunn Maschinenbau AG | German customer / Partei B | Auer Landmaschinenbau GmbH, BAUER Maschinenbau GmbH |
| Finkenstedt Medizintechnik GmbH | German customer / Partei B | none close |
| Hallerquell Getränke GmbH | German customer / Partei B | Kreuzberg Quelle Ackermann (Hallerndorf), Getränke Hell GmbH |
| Moorwiese Energie GmbH | German customer / Partei B | MB Energy, MT-Energie |
| Strelitzer Datenwerk GmbH | German customer / Partei B | DVZ Mecklenburg-Vorpommern GmbH, Stadtwerke Neustrelitz |
| Lindenhaag Bau GmbH | German customer / Partei B | Lindner-Bau GmbH, Lindel Bau GmbH |
| Zeisigtal Handelsgesellschaft mbH | German customer / Partei B | Tischlerei Zeisig |

Before adding or renaming a company in `evals/corpus/values.py`, search the new name and add a
row here.

## People

Each person in `values.PEOPLE` is a common first name paired with a less common surname. They
aren't meant to be anyone. Common names are shared by many people, so these names weren't
searched, and none refers to a real person.

## Other details

- **Places.** Real cities appear only as courts of jurisdiction (London, Dublin, München, Hamburg,
  Frankfurt am Main, Berlin).
- **Bank details.** These are visibly fake: `GB00 TELL 0000 …`, `DE00 0000 …`.
- **VAT IDs.** These follow the pattern `GB0000001nn` / `DE0000001nn` and are deliberately
  invalid.
- **Analyze-only types (M4).** The DPIA and the project status report use only the companies
  and people above. Their processing activities ("Customer support ticketing") and project
  names ("Harbour data migration") are plain descriptions, not names of anything, so they weren't
  searched.
