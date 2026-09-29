"""Extractive selection, apertus:8b against qwen2.5:14b, over twelve German questions.

The Know is extractive (A106): the model never composes a fact, it picks which retrieved sentences answer
the question. So selection accuracy is the whole of what a model contributes, and it is measurable — each
case below has a known right answer and known distractors, and the distractors are the shape that actually
misleads: **true sentences from the same source that do not answer the question asked.**

Sentences are taken from the approved and drafted entries in `content/knowledge/`. Three runs per question
per model, because a model that is wrong consistently is worse than one that is wrong occasionally: the
consistent one looks stable.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())
from eigentlich import llm  # noqa: E402

MODELS = ["apertus:8b", "qwen2.5:14b"]
RUNS = 3

# (question, sentences, the set of numbers that answer it)
CASES = [
    (
        "Darf ich mein Guthaben der Säule 3a für eine Wohnung brauchen, die ich vermiete?",
        ["Die Bindung der Säule 3a ist keine Sperre ohne Ausgang.",
         "Das Guthaben wird frühestens fünf Jahre vor dem Referenzalter der AHV fällig.",
         "Selbstgenutzt ist die entscheidende Einschränkung: eine Liegenschaft, die vermietet wird, fällt nicht darunter.",
         "Das bezogene Guthaben wird im Jahr des Bezugs besteuert, getrennt vom übrigen Einkommen.",
         "Wer über das Referenzalter hinaus erwerbstätig bleibt, kann den Bezug aufschieben."],
        {3},
    ),
    (
        "Wie viel Eigenkapital brauche ich für ein Haus?",
        ["Ein Kaufpreis ist nicht der Betrag, der angespart werden muss.",
         "Für selbstgenutztes Wohneigentum verlangen die Richtlinien mindestens 20 Prozent des Belehnungswerts aus Eigenmitteln.",
         "Der Belehnungswert ist der von der Bank geschätzte Wert, nicht zwingend der bezahlte Preis.",
         "Die Säule 3a zählt zu den harten Eigenmitteln, das Guthaben der Pensionskasse nicht.",
         "Wer die Eigenmittel zusammenhat, hat damit noch nichts über die Finanzierung gesagt."],
        {2},
    ),
    (
        "Warum rechnet die Bank mit einem Zins, den ich gar nicht zahle?",
        ["Die Institute rechnen üblicherweise mit rund 4.5 bis 5 Prozent.",
         "Eine Hypothek läuft über Jahrzehnte und wird mehrfach erneuert.",
         "Die Prüfung fragt, ob die Finanzierung auch dann noch getragen wird, wenn der Zins steigt.",
         "Unterhalt und Nebenkosten werden üblicherweise mit rund 1 Prozent des Werts pro Jahr angesetzt.",
         "Massgebend ist das Einkommen des Haushalts, der die Liegenschaft trägt."],
        {2, 3},
    ),
    (
        "Muss ich die ganze Hypothek zurückzahlen?",
        ["Eine Hypothek wird in der Schweiz nicht vollständig zurückgezahlt.",
         "Die erste Hypothek reicht bis zu zwei Dritteln des Belehnungswerts und muss nicht amortisiert werden.",
         "Die zweite Hypothek muss innert 15 Jahren zurückgezahlt werden.",
         "Die Amortisation ist Rückzahlung und nicht Aufwand.",
         "Nach der Pensionierung fällt das Erwerbseinkommen weg."],
        {1, 2, 3},
    ),
    (
        "Was kostet mich Teilzeit in der Rente?",
        ["Die Pensionskasse versichert nicht den ganzen Lohn.",
         "Weil der Koordinationsabzug ein fester Betrag ist und kein Prozentsatz, trifft er ein kleines Pensum härter.",
         "Die AHV kennt keinen Koordinationsabzug.",
         "Für Jahre, in denen Kinder betreut wurden, sieht die AHV Erziehungsgutschriften vor.",
         "Bei einer Scheidung wird das während der Ehe erworbene Guthaben der zweiten Säule geteilt."],
        {2},
    ),
    (
        "Was passiert mit meiner Pensionskasse, wenn ich selbständig werde?",
        ["Ob jemand selbständigerwerbend ist, entscheidet die Ausgleichskasse.",
         "Ohne Arbeitgeber besteht kein Obligatorium in der beruflichen Vorsorge.",
         "Das bestehende Guthaben kann bei Aufnahme einer selbständigen Erwerbstätigkeit bar bezogen werden.",
         "Wer keiner Pensionskasse angehört, darf einen deutlich höheren Betrag in die Säule 3a einzahlen.",
         "Die Beiträge werden akonto erhoben und später abgerechnet."],
        {2, 3},
    ),
]


def ask(model, question, sentences):
    prompt = (
        "Hier sind nummerierte Sätze aus einer Quelle:\n"
        + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences))
        + f"\n\nFrage: {question}\n\n"
        "Welche dieser Sätze beantworten die Frage? Antworte NUR mit den Nummern, durch Komma getrennt. "
        "Wenn keiner passt, antworte mit einem Bindestrich."
    )
    reply = llm.chat(prompt, model=model, timeout_s=180)
    text = reply if isinstance(reply, str) else reply.text
    return {int(t) for t in "".join(c if c.isdigit() else " " for c in text).split()
            if 1 <= int(t) <= len(sentences)}


for model in MODELS:
    exact = missed_answer = added_noise = 0
    total_time = 0.0
    attempts = 0
    print("=" * 96)
    print(model)
    for question, sentences, want in CASES:
        for run in range(RUNS):
            started = time.monotonic()
            try:
                got = ask(model, question, sentences)
            except Exception as error:  # noqa: BLE001
                print(f"  ERROR {type(error).__name__}: {str(error)[:60]}")
                continue
            took = time.monotonic() - started
            total_time += took
            attempts += 1
            ok = got == want
            exact += ok
            # The two failure modes are not equally bad. Missing the answering sentence shows the member
            # true text that does not answer them; adding one shows them more than they needed.
            missed_answer += bool(want - got)
            added_noise += bool(got - want)
            if run == 0:
                mark = "ok  " if ok else ("MISS" if want - got else "noisy")
                print(f"  {mark} want {sorted(want)} got {sorted(got)}  {took:5.1f}s  {question[:52]}")
    print(f"  --> exact {exact}/{attempts} · missed the answering sentence {missed_answer} · "
          f"added a non-answer {added_noise} · {total_time / max(1, attempts):.1f}s per call")
    print()
