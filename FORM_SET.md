# Initial Form Set

The initial manifest focuses on commonly used individual forms plus Form 1042,
Form 1042-S, and related withholding/certificate forms.

## Individual Core

- 1040
- 1040 Schedule 1
- 1040 Schedule 2
- 1040 Schedule 3
- 1040 Schedule A
- 1040 Schedule B
- 1040 Schedule C
- 1040 Schedule D
- 1040 Schedule E
- 1040 Schedule SE
- 8949
- 8863
- 8889
- 8962
- 2441
- Schedule 8812
- 5695
- 8283
- 4562
- 8829
- 4868
- W-4
- W-9

## Taxpayer Identification And Certification

- W-9 (SP)
- W-9S
- W-10
- W-13
- W-14

## International Information Reporting

- 3520

## 1042 And Related

- 1042
- 1042-S
- 1042-T
- W-8BEN
- W-8BEN-E
- W-8CE
- W-8ECI
- W-8EXP
- W-8IMY
- 8233
- 8804
- 8805
- 8813

Each form is processed independently by running:

```sh
python3 scripts/process_form.py <form-id> --repo-root "$PWD"
```
