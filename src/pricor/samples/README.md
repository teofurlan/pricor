# Sample price lists

Synthetic lists of a fictional Argentine hardware and electrical distributor
("Distribuidora Ejemplo"), so anyone can try Pricor without a supplier file. Nothing here
comes from a real supplier: everything is generated.

| File | Contents |
| --- | --- |
| `distribuidora-ejemplo-semana-1.xlsx` | About 300 products in 8 sections. A title block and blank rows above the header, section rows (`*** ILUMINACIÓN ***`), an internal code (`CODIGO`) empty for part of the products next to a supplier code (`COD_PROV`) that is always filled, prices without VAT, a currency column mixing `$` and `u$s`, ordinary discounts (`10%`) and conditional quantity discounts (`10% x 10 UN`) in separate columns. |
| `distribuidora-ejemplo-semana-2-simulada.xlsx` | The same products one week later, marked SIMULADA in the file name and the title row: price rises and drops, four new and four dropped products, one price tripled, and two columns (`COD_PROV` and `DESCRIPCION`) swapped. |

They are served by `GET /samples` and `GET /samples/{id}`, and shipped inside the package.

## Regenerate

```
uv run python tools/samples/generate.py
```

The output is deterministic (fixed seed, fixed workbook properties and ZIP timestamps), so
running it again rewrites byte-identical files. A test fails when the committed files differ
from what the generator produces.
