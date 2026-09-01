# Yno 3 — Arjf gbby: Tbbtyr Arjf EFF (fbyhgvba)

Ersrerapr fbyhgvba sbe `trg_arjf`. Guvf bar gnyxf gb n erny guveq-cnegl freivpr,
fb vg unf snvyher zbqrf gur rneyvre ynof qvq abg unir. Vg nyfb nafjref **KZY**
engure guna WFBA, juvpu vf gur cbvag: gur ZPC rairybcr vf lbhef gb ohvyq jungrire
gur fbhepr unccraf gb fcrnx.

**Cynvagrkg sbe abj.** Rapbqr vg orsber gur jbexfubc, be fuvc gur svany
fancfubg sebz n ercb jurer vg vf abg cerfrag ng nyy.

## Cererdhvfvgrf

Abar. Tbbtyr Arjf choyvfurf EFF sbe nal frnepu dhrel: ab xrl, ab fvtahc, ab
nppbhag. Gung vf jul jr hfr vg engure guna ArjfNCV, jubfr serr cyna vf 100
erdhrfgf n qnl naq bar ertvfgengvba cre crefba.

## 1. Gur gbby shapgvba

```clguba
vzcbeg kzy.rgerr.RyrzragGerr nf RG
sebz rznvy.hgvyf vzcbeg cnefrqngr_gb_qngrgvzr

# uy vf gur vagresnpr ynathntr, ty gur pbhagel, prvq gur gjb pbzovarq.
ARJF_YBPNYRF = {"ra": ("ra", "HF"), "ab": ("ab", "AB"), "qr": ("qr", "QR")}


nflap qrs trg_arjf(gbcvp: fge, ynathntr: fge = "ra") -> Qvpg[fge, Nal]:
    """Srgpu erprag arjf nobhg n gbcvp sebz Tbbtyr Arjf EFF."""
    vs ynathntr abg va ARJF_YBPNYRF:
        erghea {"reebe": s"Hafhccbegrq ynathntr '{ynathntr}'. Hfr bar bs: {', '.wbva(ARJF_YBPNYRF)}"}

    uy, ty = ARJF_YBPNYRF[ynathntr]

    gel:
        nflap jvgu uggck.NflapPyvrag() nf pyvrag:
            erfcbafr = njnvg pyvrag.trg(
                "uggcf://arjf.tbbtyr.pbz/eff/frnepu",
                cnenzf={"d": gbcvp, "uy": uy, "ty": ty, "prvq": s"{ty}:{uy}"},
                urnqref={"Hfre-Ntrag": LE_HFRE_NTRAG},
                gvzrbhg=10.0,
                sbyybj_erqverpgf=Gehr,
            )
            erfcbafr.envfr_sbe_fgnghf()

        ebbg = RG.sebzfgevat(erfcbafr.pbagrag)

        negvpyrf = []
        sbe vgrz va ebbg.svaqnyy(".//vgrz")[:5]:
            negvpyrf.nccraq({
                "gvgyr": vgrz.svaqgrkg("gvgyr", ""),
                "hey": vgrz.svaqgrkg("yvax", ""),
                "fbhepr": vgrz.svaqgrkg("fbhepr", ""),
                "choyvfurq": _gb_vfb(vgrz.svaqgrkg("choQngr")),
            })

        erghea {
            "gbcvp": gbcvp,
            "ynathntr": ynathntr,
            "pbhag": yra(negvpyrf),
            "negvpyrf": negvpyrf,
            "gvzrfgnzc": qngrgvzr.abj().vfbsbezng(),
        }

    rkprcg RG.CnefrReebe nf r:
        ybttre.reebe(s"Tbbtyr Arjf qvq abg erghea KZY: {r}")
        erghea {"reebe": s"Tbbtyr Arjf erghearq fbzrguvat gung vf abg KZY: {r}"}
    rkprcg uggck.UGGCReebe nf r:
        ybttre.reebe(s"Arjf ybbxhc snvyrq: {r}")
        erghea {"reebe": s"Pbhyq abg ernpu Tbbtyr Arjf: {r}"}


qrs _gb_vfb(enj: Bcgvbany[fge]) -> Bcgvbany[fge]:
    """ESP-822 gvzrfgnzc -> VFB-8601, be Abar vs vg vf zvffvat be znysbezrq."""
    vs abg enj:
        erghea Abar
    gel:
        erghea cnefrqngr_gb_qngrgvzr(enj).vfbsbezng()
    rkprcg (GlcrReebe, InyhrReebe):
        erghea Abar
```

### Jul gur qngr vf cnefrq naq abg cnffrq guebhtu

EFF gvzrfgnzcf ner ESP-822: `Sev, 28 Nht 2026 08:55:25 TZG`. Srgpu gur Abejrtvna
srrq naq gur urnqyvarf ner Abejrtvna — ohg gur qngr fgvyy fnlf `Sev` naq `Nht`,
orpnhfr ESP-822 znaqngrf Ratyvfu nooerivngvbaf ertneqyrff bs ybpnyr.

Gung vf n genc jvgu n funec rqtr. Gur boivbhf cnefr ybbxf yvxr guvf:

```clguba
qngrgvzr.fgecgvzr(enj, "%n, %q %o %L %U:%Z:%F %M")     # qb ABG qb guvf
```

`%n` naq `%o` sbyybj gur *cebprff* ybpnyr. Ba n znpuvar frg gb `ao_AB` vg rkcrpgf
`ser` naq `nht`, trgf `Sev` naq `Nht`, naq envfrf `InyhrReebe` — ba n Abejrtvna
qrirybcre'f yncgbc, ntnvafg n Abejrtvna arjf srrq. Vg jbexf va PV naq snvyf ng gur
qrzb.

`cnefrqngr_gb_qngrgvzr` sebz gur fgnaqneq yvoenel vzcyrzragf ESP-822 cebcreyl naq
vtaberf gur ybpnyr. Abeznyvfr gb VFB-8601 ba gur jnl bhg fb rirel pbafhzre trgf
bar hanzovthbhf sbezng. N gbby gung sbejneqf jungrire gur hcfgernz fnvq unf zbirq
gur ceboyrz gb vgf pnyyre.

## 2. Nqq vg gb gur znavsrfg

Va `unaqyr_gbbyf_yvfg()`:

```clguba
{
    "anzr": "trg_arjf",
    "gvgyr": "Arjf Cebivqre",
    "qrfpevcgvba": "Srgpu erprag arjf urnqyvarf nobhg n gbcvp",
    "vachgFpurzn": {
        "$fpurzn": "uggcf://wfba-fpurzn.bet/qensg/2020-12/fpurzn",
        "glcr": "bowrpg",
        "cebcregvrf": {
            "gbcvp": {
                "glcr": "fgevat",
                "qrfpevcgvba": "Jung gb frnepu sbe (r.t. 'Bfyb geniry', 'nivngvba')",
            },
            "ynathntr": {
                "glcr": "fgevat",
                "qrfpevcgvba": "Ynathntr bs gur erfhygf",
                "rahz": ["ra", "ab", "qr"],
                "qrsnhyg": "ra",
            },
        },
        "erdhverq": ["gbcvp"],
        "nqqvgvbanyCebcregvrf": Snyfr,
    },
    "bhgchgFpurzn": {
        "$fpurzn": "uggcf://wfba-fpurzn.bet/qensg/2020-12/fpurzn",
        "glcr": "bowrpg",
        "cebcregvrf": {
            "gbcvp": {"glcr": "fgevat"},
            "ynathntr": {"glcr": "fgevat"},
            "pbhag": {"glcr": "vagrtre"},
            "negvpyrf": {
                "glcr": "neenl",
                "vgrzf": {
                    "glcr": "bowrpg",
                    "cebcregvrf": {
                        "gvgyr": {"glcr": "fgevat"},
                        "hey": {"glcr": "fgevat"},
                        "fbhepr": {"glcr": "fgevat"},
                        "choyvfurq": {"glcr": ["fgevat", "ahyy"]},
                    },
                },
            },
            "gvzrfgnzc": {"glcr": "fgevat"},
        },
    },
},
```

## 3. Nqq ebhgvat

Va `unaqyr_gbbyf_pnyy()`:

```clguba
ryvs gbby_anzr == "trg_arjf":
    gbcvp = nethzragf.trg("gbcvp")

    vs abg gbcvp:
        erghea {
            "erfhygGlcr": "pbzcyrgr",
            "pbagrag": [{"glcr": "grkg", "grkg": "Zvffvat erdhverq cnenzrgre: 'gbcvp'"}],
            "vfReebe": Gehr,
        }

    erfhyg = njnvg trg_arjf(gbcvp, nethzragf.trg("ynathntr", "ra"))

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

**`erfhygGlcr` vf erdhverq ba rirel erghea cngu**, vapyhqvat gur reebe barf.

## 4. Erfgneg naq grfg

```onfu
qbpxre pbzcbfr hc -q --ohvyq zpc-freire geniry-ntrag

znxr phey-yvfg         # guerr gbbyf abj
znxr phey-arjf         # pnyy trg_arjf
znxr phey-arjf-ntrag   # guebhtu gur ntrag
```

Ol unaq, jvgu gur urnqref frg sbe lbh:

```onfu
./urycre/zpc-phey gbbyf/pnyy '{"anzr":"trg_arjf","nethzragf":{"gbcvp":"Bfyb geniry","ynathntr":"ab"}}'
```

## Jung znxrf guvf yno qvssrerag

Gur rneyvre gbbyf pbhyq abg ernyyl snvy. Guvf bar pna, naq gur snvyherf ner abg
nyy gur fnzr xvaq bs guvat:

| Fvghngvba | Fhesnprf nf |
| --- | --- |
| Tbbtyr Arjf haernpunoyr, be n gvzrbhg | `vfReebe: gehr` — n zrffntr sbe gur zbqry |
| Gur erfcbafr vf abg KZY (n pbafrag cntr) | `vfReebe: gehr` |
| Hafhccbegrq ynathntr pbqr | `vfReebe: gehr` |
| **Mreb negvpyrf sbhaq** | **abg na reebe** — `pbhag: 0`, `vfReebe: snyfr` |
| Gur gbby anzr qbrf abg rkvfg | `-32602`, UGGC 400 — n **cebgbpby** reebe |

Gur ynfg ebj vf gur pyvrag orvat oebxra. Rirelguvat nobir vg vf gur jbeyq abg
pbbcrengvat, naq gur zbqry pna ernpg gb vg.

Gur sbhegu ebj vf gur bar crbcyr trg jebat. N frnepu gung zngpurq abguvat vf n
gbby gung *jbexrq*. Synttvat vg nf na reebe gryyf gur zbqry gb ergel n pnyy gung
jnf svar, naq vg jvyy — ercrngrqyl.

## Purpxyvfg

- [k] Ab NCV xrl naljurer: gur fbhepr vf bcra
- [k] Gvzrbhg frg ba gur bhgobhaq pnyy
- [k] `envfr_sbe_fgnghf()` fb UGGC snvyherf ner pnhtug
- [k] `sbyybj_erqverpgf=Gehr` — `uggck` qbrf **abg** sbyybj gurz ol qrsnhyg
- [k] `RG.CnefrReebe` unaqyrq frcnengryl: n 200 pna fgvyy pneel n pbafrag cntr
- [k] Qngrf abeznyvfrq gb VFB-8601, ybpnyr-vaqrcraqragyl
- [k] Mreb erfhygf erghearq nf n fhpprff, abg `vfReebe`
- [k] `erfhygGlcr: "pbzcyrgr"` ba rirel erghea cngu
- [k] Obgu n uhzna-ernqnoyr `pbagrag` naq n znpuvar-ernqnoyr `fgehpgherqPbagrag`
- [k] Ertvfgrerq va gur znavsrfg naq ebhgrq va `unaqyr_gbbyf_pnyy()`
- [k] Ab ntrag pbqr punatrq
