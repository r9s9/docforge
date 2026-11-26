# Hand-made documents (brief §5.3)

This set holds 10–20 documents made by hand in Word, messier than the generated ones:
- tracked changes that were accepted
- text pasted from an email
- broken styles
- a document converted from PDF

Each file is checked against one of the corpus templates. Use only documents you wrote
yourself, never employer, client or third-party ones.

## Files

```
handmade/
  <name>.docx           the document, made in Word
  <name>.labels.yaml    what you changed, labelled by you
```

## Labels

```yaml
document: dv_tracked_changes.docx
pair: service_agreement_de          # which corpus template it is checked against
made_with: "Word 365; tracked changes accepted; one paragraph pasted from Outlook"
deviations:                          # [] for a clean document
  - kind: changed_fixed              # the DocForge kind you expect, or "none"
    material: true
    anchor: "Gerichtsstand ist"      # a short quote from the template element you changed
    note: "Gerichtsstand changed to Köln"
  - kind: none
    material: false
    anchor: "§ 4 Haftungsbeschränkung"
    note: "heading re-typed with a different style"
```

### What each key means
- **`pair`** is one of the corpus types, for example `service_agreement_de`, `nda_en` or
  `invoice_de`.
- **`anchor`** is a quote of the template text you changed. It stands in for the generator's
  locators, which a hand-made file doesn't have. The runner finds the template element whose
  text contains the quote, and it stops with an error if no element matches or more than one
  does.
- **`material`** says whether a reviewer must notice the change, which is what the AI judge is
  graded against.

### Status
The format is fixed as of M1. The comply runner reads these files once some are committed. For
now the folder holds only this README.
