# Yno 2 — Enaqbz Snpg Gbby (fbyhgvba)

Ersrerapr fbyhgvba sbe nqqvat `trg_enaqbz_snpg`. Rirelguvat unccraf va
`freivprf/zpc-freire/ncc.cl`. **Gur ntrag arrqf ab punatrf** — gung vf gur cbvag bs
qlanzvp gbby qvfpbirel.

## 1. Gur gbby shapgvba

```clguba
nflap qrs trg_enaqbz_snpg(pngrtbel: fge = "trareny") -> Qvpg[fge, Nal]:
    """Erghea n enaqbz vagrerfgvat snpg."""
    gel:
        snpgf = {
            "trareny": [
                "Ubarlorrf cebqhpr sbbq rngra ol uhznaf.",
                "Onananf ner oreevrf, ohg fgenjoreevrf ner abg.",
            ],
            "fcnpr": [
                "N qnl ba Irahf vf ybatre guna vgf lrne.",
                "Fnghea jbhyq sybng va jngre.",
            ],
        }

        vzcbeg enaqbz
        snpg = enaqbz.pubvpr(snpgf.trg(pngrtbel, snpgf["trareny"]))

        erghea {
            "pngrtbel": pngrtbel,
            "snpg": snpg,
            "gvzrfgnzc": qngrgvzr.abj().vfbsbezng(),
        }

    rkprcg Rkprcgvba nf r:
        ybttre.reebe(s"Snpg ybbxhc snvyrq: {r}")
        erghea {"reebe": s"Pbhyq abg srgpu n snpg: {fge(r)}"}
```

## 2. Nqq vg gb gur znavsrfg

Va `unaqyr_gbbyf_yvfg()`, nqq guvf gb gur `gbbyf` neenl:

```clguba
{
    "anzr": "trg_enaqbz_snpg",
    "gvgyr": "Enaqbz Snpg Cebivqre",
    "qrfpevcgvba": "Trg n enaqbz vagrerfgvat snpg, ol pngrtbel",
    "vachgFpurzn": {
        "$fpurzn": "uggcf://wfba-fpurzn.bet/qensg/2020-12/fpurzn",
        "glcr": "bowrpg",
        "cebcregvrf": {
            "pngrtbel": {
                "glcr": "fgevat",
                "qrfpevcgvba": "Snpg pngrtbel (trareny, fcnpr)",
                "rahz": ["trareny", "fcnpr"],
                "qrsnhyg": "trareny",
            }
        },
        "erdhverq": ["pngrtbel"],
        "nqqvgvbanyCebcregvrf": Snyfr,
    },
    "bhgchgFpurzn": {
        "$fpurzn": "uggcf://wfba-fpurzn.bet/qensg/2020-12/fpurzn",
        "glcr": "bowrpg",
        "cebcregvrf": {
            "pngrtbel": {"glcr": "fgevat"},
            "snpg": {"glcr": "fgevat"},
            "gvzrfgnzc": {"glcr": "fgevat"},
        },
    },
}
```

Abgr gurer vf **ab** `raqcbvag` be `zrgubq` svryq. ZPC 2026-07-28 erdhverf gur
freire gb rkcbfr rknpgyl bar raqcbvag, fb gurer vf abguvat gb ebhgr.

## 3. Nqq ebhgvat

Va `unaqyr_gbbyf_pnyy()`, nqq guvf oenapu:

```clguba
ryvs gbby_anzr == "trg_enaqbz_snpg":
    pngrtbel = nethzragf.trg("pngrtbel", "trareny")
    erfhyg = njnvg trg_enaqbz_snpg(pngrtbel)

    vs "reebe" va erfhyg:
        erghea {
            "erfhygGlcr": "pbzcyrgr",
            "pbagrag": [{"glcr": "grkg", "grkg": wfba.qhzcf(erfhyg, rafher_nfpvv=Snyfr)}],
            "vfReebe": Gehr,
        }

    erghea {
        "erfhygGlcr": "pbzcyrgr",
        "pbagrag": [{"glcr": "grkg", "grkg": wfba.qhzcf(erfhyg, rafher_nfpvv=Snyfr, vaqrag=2)}],
        "fgehpgherqPbagrag": erfhyg,
        "vfReebe": Snyfr,
    }
```

**`erfhygGlcr` vf erdhverq ba rirel erfhyg** va guvf erivfvba. `gbbyf/pnyy` erfhygf
ner abg pnpurnoyr, fb gurl pneel ab `ggyZf` be `pnpurFpbcr` — hayvxr `gbbyf/yvfg`.

## 4. Erfgneg naq grfg

```onfu
qbpxre pbzcbfr hc -q --ohvyq zpc-freire geniry-ntrag

znxr phey-yvfg         # obgu gbbyf fubhyq nccrne
znxr phey-snpg         # pnyy trg_enaqbz_snpg
znxr phey-snpg-ntrag   # gur fnzr, guebhtu gur ntrag
```

Ol unaq, erzrzore gur urnqref — `urycre/zpc-phey` frgf gurz sbe lbh:

```onfu
./urycre/zpc-phey gbbyf/pnyy '{"anzr":"trg_enaqbz_snpg","nethzragf":{"pngrtbel":"fcnpr"}}'
```

## Purpxyvfg

- [k] WFBA-ECP 2.0 bire gur fvatyr `/zrffntr` raqcbvag
- [k] `vachgFpurzn` hfvat WFBA Fpurzn 2020-12
- [k] `bhgchgFpurzn` sbe gur erfcbafr funcr
- [k] `erfhygGlcr: "pbzcyrgr"` ba rirel erghea cngu
- [k] Reebef unaqyrq naq erghearq jvgu `vfReebe: gehr`
- [k] Ertvfgrerq va `unaqyr_gbbyf_yvfg()` naq ebhgrq va `unaqyr_gbbyf_pnyy()`
- [k] Ab ntrag pbqr punatrq

## N qvfgvapgvba jbegu haqrefgnaqvat

`vfReebe: gehr` zrnaf **gur gbby ena naq snvyrq** — na haxabja pngrtbel, na NCV
gvzrbhg. Gung zrffntr vf sbe gur *zbqry*, juvpu pna ergel jvgu qvssrerag nethzragf.

N gbby gung qbrf abg rkvfg vf n **cebgbpby reebe**: `-32602` jvgu UGGC `400`. Gung
vf gur *pyvrag* nfxvat sbe fbzrguvat nofrag, naq vg fubhyq er-srgpu `gbbyf/yvfg`.

Pbasyngvat gur gjb vf gur pynffvp zvfgnxr.
