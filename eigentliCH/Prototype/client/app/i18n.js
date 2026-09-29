// UI strings, de-CH default (A12).
//
// These are the client's own chrome — labels, buttons, section headings. They are NOT the role
// definitions or the destination phrase: those are content records the server owns, because they are
// product statements rather than interface furniture. Keeping the two apart is why a translator can work
// on this file without touching a definition that came from the published model.
//
// R-143: no mountain, hut, tour, summit or climb vocabulary, in either language. A backend test enforces
// that on the content records; this file is small enough to read.
//
// C-07: no points, score, streak, badge, level-number, leaderboard or daily-goal vocabulary. Note what is
// absent: there is no string here for "x of y", "complete", "progress" or "remaining", because there is
// no screen that may say one.

const STRINGS = {
  de: {
    'grid.eyebrow': 'Plan',
    'grid.title': 'Ihre Positionen',
    'grid.lede':
      'Vier Rollen über zwei Arten von Kapital. Was Sie können und was Sie besitzen stehen nebeneinander, '
      + 'weil sie sich gegenseitig ersetzen können.',
    'grid.provisional': 'Definitionen vorläufig',
    'grid.one_position': 'Eine Position erfasst.',
    'grid.n_positions': 'Erfasste Positionen: {n}.',
    'capital.human': 'Menschliches Kapital',
    'capital.financial': 'Finanzielles Kapital',
    'cell.add': 'Position erfassen',
    'cell.what_is_this': 'Was gehört hierher?',
    'position.inactive': 'nicht mehr aktiv',
    'unit.chf_per_year': 'CHF pro Jahr',
    'unit.share_of_total': 'Anteil am Ganzen',
    'form.title': 'Position erfassen',
    'form.label': 'Wie nennen Sie diese Position?',
    'form.label_hint': 'Ein kurzer Name, den Sie in einem Jahr wiedererkennen.',
    'form.description': 'Beschreibung (optional)',
    'form.magnitude': 'Betrag (optional)',
    'form.magnitude_hint': 'Leer lassen, wenn kein Frankenbetrag passt. Eine Position ohne Betrag ist eine vollwertige Position.',
    'form.unit': 'Worauf bezieht sich der Betrag?',
    'form.unit_hint': 'Wird nie geraten, deshalb steht die Frage hier. Ein Jahresbetrag und ein Anteil am Ganzen sind nicht dasselbe. Einen Monatsbetrag rechnen Sie bitte auf das Jahr um.',
    'form.unit_choose': 'Bitte auswählen',
    'form.unit_missing': 'Bitte geben Sie an, worauf sich der Betrag bezieht. Ein Betrag ohne diese Angabe wäre eine Zahl, die niemand lesen kann.',
    'form.time_basis': 'Zeitaufwand',
    'form.time_basis_hint': 'Zum Beispiel 42 Stunden pro Woche. Bei menschlichem Kapital ist Zeit die bindende Grenze.',
    'form.tags': 'Einordnung (optional)',
    'form.tags_hint': 'Frei formuliert. Diese Angaben werden gespeichert und heute nicht ausgewertet.',
    'form.decision': 'Was halten wir fest?',
    'form.decision_hint': 'Jede Änderung am Plan wird mit ihrer Begründung festgehalten. Das bleibt Ihr Protokoll.',
    'form.question': 'Frage',
    'form.choice': 'Entscheid',
    'form.default_question': '{role}: Position erfassen?',
    'form.save': 'Erfassen',
    'form.cancel': 'Abbrechen',
    'tag.client_type': 'Art der Auftraggeber',
    'tag.skill': 'Fähigkeit',
    'tag.reputation_basis': 'Worauf beruht der Ruf',
    'tag.sector': 'Branche',
    'tag.time_basis': 'Zeitliche Grundlage',
    // ---- A11: the chrome, and the three states of getting in ----
    //
    // The chrome strings exist because `index.html` used to hard-code German into the doors and the skip
    // link, so an English member kept a German header — A12's gap, recorded in A70 with this file named.
    // They are rewritten by `main.js::applyChrome` from `data-i18n` attributes.
    'chrome.skip': 'Zum Inhalt springen',
    'chrome.nav_label': 'Hauptnavigation',
    'chrome.door_vault': 'Tresor',
    'chrome.home': 'Zur Frage',
    'chrome.door_plan': 'Plan & Lebensereignisse',
    // The fourth door, added 31 August 2026. `GET /api/befund` returned a complete six-section report and
    // there was no way for a member to reach it: the machinery existed and no surface rendered it, which is
    // why the owner tested the application again and said "there is still no output". The door is the fix,
    // and it is short on purpose — a door is a name, and the surface itself carries the sentence.
    'chrome.door_befund': 'Befund',
    'chrome.door_know': 'Wissen',
    'chrome.door_market': 'Marktplatz',
    // ---- A12 / A26: the language switch, in the browser chrome ----
    //
    // The two option labels are NOT here and are not translated. A member looking for their language looks
    // for the word in that language — "Deutsch", "English" — and a switch that says "German" to a German
    // reader is a switch they have to work out. Endonyms are the convention for the same reason street
    // signs are not translated. What needs a string is the group's label and what happens after a change.
    'chrome.language': 'Sprache',
    'language.changed': 'Die Sprache ist umgestellt.',
    'language.not_saved': 'Die Sprache konnte nicht gespeichert werden. Es gilt weiterhin die bisherige.',
    'language.this_device_only': 'Vor der Anmeldung gilt die Wahl nur für dieses Fenster — es gibt noch kein Konto, auf dem sie liegen könnte.',
    'session.sign_out': 'Abmelden',
    'session.signed_out': 'Sie sind abgemeldet.',
    'login.eyebrow': 'eigentliCH',
    'login.title': 'Anmelden',
    'login.lede': 'Ihre Unterlagen und Ihr Plan liegen hinter Ihrem eigenen Passwort. Niemand sonst sieht sie.',
    'login.email': 'E-Mail-Adresse',
    'login.password': 'Passwort',
    'login.submit': 'Anmelden',
    'login.no_account': 'Noch kein Zugang?',
    'login.register': 'Zugang eröffnen',
    'login.forgotten': 'Passwort vergessen? eigentliCH läuft auf diesem Gerät, und wer den Rechner betreibt, kann ein neues setzen. Es gibt bewusst keine E-Mail mit einem Link.',
    'register.eyebrow': 'eigentliCH',
    'register.title': 'Zugang eröffnen',
    'register.lede': 'Vier Angaben. Danach melden Sie sich mit dem Passwort an, das Sie gerade gewählt haben.',
    'register.name': 'Wie sollen wir Sie nennen?',
    'register.name_hint': 'Ein Name, den Sie auf Ihrem eigenen Bildschirm sehen möchten.',
    'register.age': 'Wie alt sind Sie?',
    'register.age_hint': 'Ab 18 Jahren.',
    'register.email': 'E-Mail-Adresse',
    'register.email_hint': 'Damit melden Sie sich an. Sie bleibt auf diesem Rechner.',
    'register.password': 'Passwort',
    'register.password_hint': 'Mindestens 12 Zeichen. Länge ist die einzige Regel — Vorschriften zu Gross- und Kleinschreibung führen zu kürzeren, leichter zu erratenden Passwörtern.',
    'register.submit': 'Zugang eröffnen',
    'register.cancel': 'Zurück zur Anmeldung',
    'register.now_sign_in': 'Zugang eröffnet. Melden Sie sich jetzt an.',
    'password.eyebrow': 'eigentliCH',
    'password.title': 'Neues Passwort wählen',
    'password.lede': 'Dieser Zugang wurde mit einem Passwort eingerichtet, das nur für die erste Anmeldung gilt. Wählen Sie jetzt Ihr eigenes.',
    'password.current': 'Bisheriges Passwort',
    'password.current_hint': 'Auch hier nötig: sonst würde ein gestohlener Zugang genügen, um das Passwort zu ändern.',
    'password.new': 'Neues Passwort',
    'password.new_hint': 'Mindestens 12 Zeichen. Das bisherige Passwort funktioniert danach nicht mehr.',
    'password.repeat': 'Neues Passwort wiederholen',
    'password.submit': 'Passwort setzen',
    'password.mismatch': 'Die beiden Eingaben stimmen nicht überein.',
    'password.sign_out': 'Abmelden',
    // ---- A40: the curator's own way in ----
    //
    // A separate population and a separate table, so a separate screen. The `password.*` block above is
    // reused verbatim for the curator's forced change rather than duplicated: it is the same moment, the
    // same three fields and the same rule about the current password, and two copies of that copy would
    // be two copies to keep in step.
    //
    // `curator.no_token` is the one string on any of these screens that had to be written rather than
    // borrowed. A40 issues no curator token, so the honest thing to tell a curator is what that costs
    // them — the credential lives in the window and a reload ends the session.
    'curator.door_hint': 'Sie kuratieren für eigentliCH?',
    'curator.door': 'Zur Kurator-Anmeldung',
    'curator.eyebrow': 'eigentliCH',
    'curator.title': 'Kurator-Anmeldung',
    'curator.lede': 'Kuratoren melden sich mit eigenen Zugangsdaten an, die in einer eigenen Tabelle liegen. Das hier ist nicht die Anmeldung für Mitglieder.',
    'curator.email': 'E-Mail-Adresse',
    'curator.email_hint': 'Die Adresse für Kuratoren, nicht die für Mitglieder.',
    'curator.password': 'Passwort',
    'curator.submit': 'Anmelden',
    'curator.back': 'Zurück zur Anmeldung für Mitglieder',
    'curator.sign_out': 'Abmelden',
    'curator.signed_out': 'Sie sind abgemeldet. Die Zugangsdaten sind aus diesem Fenster entfernt.',
    'curator.password_changed': 'Das Passwort ist gesetzt. Das bisherige funktioniert nicht mehr.',
    'curator.workbench_eyebrow': 'Kuratorium',
    'curator.workbench_title': 'Freigaben',
    'curator.workbench_lede': 'Hier stehen die Mitglieder, die Ihnen Einsicht gegeben haben, und was diese Einsicht umfasst.',
    'curator.identity': 'Angemeldet als',
    'curator.role': 'Rolle',
    'curator.no_role': 'Ohne Rollenbezeichnung',
    'curator.no_token': 'Für Kuratoren wird kein Sitzungsschlüssel ausgegeben. Ihre Zugangsdaten bleiben in diesem Fenster und gehen bei jeder Abfrage neu mit; nach einem Neuladen der Seite melden Sie sich wieder an.',
    'curator.grant_model': 'Einsicht gibt das Mitglied selbst, für benannte Bereiche und auf Zeit. Es gibt kein «alles» und kein «bis auf Widerruf», und das Mitglied nimmt die Einsicht jederzeit mit sofortiger Wirkung zurück.',
    'curator.nothing_granted': 'Kein Mitglied hat Ihnen zurzeit Einsicht gegeben. Deshalb steht hier nichts: es gibt von hier aus keinen Weg in Unterlagen, für die keine Freigabe vorliegt.',
    'curator.scope': 'Umfang',
    'curator.expires': 'Läuft ab am',
    'curator.reload': 'Freigaben neu abfragen',
    'curator.reloaded': 'Die Freigaben sind neu abgefragt.',
    'curator.open_consultation': 'Beratung eröffnen',
    'curator.consultation_opened': 'Beratung eröffnet. Der Eintrag ist geschrieben.',
    'curator.audit_note': 'Jede eröffnete Beratung schreibt einen Eintrag in ein Protokoll, das nachträglich nicht geändert und nicht gelöscht werden kann.',
    'curator.granted': 'Freigegeben',
    'curator.withheld': 'Nicht freigegeben',
    'curator.member': 'Mitglied',
    'curator.refused': 'Diese Abfrage wurde abgelehnt. Die Begründung steht darunter, so wie der Server sie geschrieben hat.',
    // R-210's scope vocabulary. The names come from `GRANTABLE` on the server; these are the words for
    // them, and a test walks that tuple against this list so neither side can grow a member alone.
    'curator.scope_positions': 'Positionen',
    'curator.scope_goals': 'Ziele',
    'curator.scope_decisions': 'Entscheide',
    'curator.scope_vault': 'Ablage',
    'curator.scope_action_items': 'Vorbereitete Entscheide',
    // ---- S-12: was das Mitglied geteilt hat, und die Beratung selbst (R-210, R-211, R-212, C-10) ----
    'curator.sections': 'Was das Mitglied geteilt hat',
    'curator.section_empty': 'In diesem Bereich ist nichts erfasst.',
    'curator.vault_no_bytes':
      'Das Verzeichnis der Ablage, ohne die Dateien selbst. Eine Freigabe für die Ablage öffnet das '
      + 'Verzeichnis und nicht die Dokumente.',
    'curator.no_sections':
      'Es ist kein Bereich freigegeben, aus dem sich etwas anzeigen liesse.',
    'curator.consultation': 'Diese Beratung',
    'curator.consultation_ref': 'Beratung',
    'curator.log': 'Protokoll dieser Beratung',
    'curator.log_opened': 'Eröffnet',
    'curator.log_note': 'Notiz',
    'curator.log_closed': 'Abgeschlossen',
    'curator.notes_redacted':
      'Der Wortlaut der Notizen ist ohne gültige Freigabe nicht lesbar. Dass eine Notiz geschrieben wurde, '
      + 'bleibt sichtbar.',
    'curator.note': 'Notiz zur Beratung',
    'curator.note_hint':
      'Die Notiz wird an das Protokoll angehängt und lässt sich danach nicht mehr ändern. Sie gilt als '
      + 'Material des Mitglieds und ist nur mit gültiger Freigabe lesbar.',
    'curator.note_add': 'Notiz anhängen',
    'curator.note_added': 'Die Notiz ist angehängt.',
    'curator.note_missing': 'Eine leere Notiz wird nicht gesendet.',
    'curator.recommend_heading': 'Empfehlung festhalten',
    'curator.recommend_hint':
      'Eine Empfehlung kommt von der Person, die kuratiert, und nie von eigentliCH. Sie wird als Entscheid '
      + 'mit Ihrem Namen daran festgehalten und gehört danach zum Verlauf des Mitglieds.',
    'curator.recommend_question': 'Worum ging es?',
    'curator.recommend_choice': 'Was Sie festhalten',
    'curator.recommend_reasoning': 'Begründung',
    'curator.recommend_submit': 'Als Entscheid festhalten',
    'curator.recommend_done': 'Festgehalten, mit Ihrem Namen daran.',
    'curator.recommend_missing': 'Frage und Festhaltung werden beide gebraucht.',
    'curator.close_heading': 'Beratung abschliessen',
    'curator.close_hint':
      'Jede Beratung wird mit ihrem Ergebnis abgeschlossen. Ohne Ergebnis lässt sie sich nicht schliessen, '
      + 'und ein Ergebnis wird hier nicht vorgegeben.',
    'curator.close_outcome': 'Ergebnis',
    'curator.close_outcome_missing': 'Ohne Ergebnis wird nichts gesendet.',
    'curator.close_note': 'Schlussbemerkung',
    'curator.close_liability': 'Haftungsfrage vermerken',
    'curator.close_submit': 'Beratung abschliessen',
    'curator.closed': 'Die Beratung ist abgeschlossen. Das Ergebnis steht im Protokoll.',
    'curator.still_open': 'Noch offen',
    'onboarding.eyebrow': 'Erstgespräch',
    'onboarding.title': 'Ein paar Fragen',
    'onboarding.lede': 'Nur die erste ist nötig. Was Sie überspringen, können Sie später im Raster erfassen.',
    'onboarding.why': 'Warum diese Frage?',
    'onboarding.skip': 'Überspringen',
    'onboarding.next': 'Weiter',
    'onboarding.finish': 'Fertig — Raster anzeigen',
    'onboarding.saved': 'Gespeichert.',
    // S-01's goal question offers the templates and fills the goal out, rather than taking free text and
    // storing it as a name with no template.
    'onboarding.goal_template': 'Ziel',
    'onboarding.goal_name': 'Wie nennen Sie dieses Ziel?',
    'onboarding.goal_name_hint': 'Der Name der Vorlage ist eingesetzt. Sie dürfen ihn überschreiben — er ist Ihr Ziel, nicht unsere Vorlage.',
    'nav.plan': 'Positionen',
    'nav.containers': 'Ziele',
    'regime.reading_crisis_tail': 'Wahrscheinlichkeit einer Krise',
    'regime.reading_bimodal': 'Zwei mögliche Lagen statt einer',
    'regime.yes': 'ja',
    'regime.no': 'nein',
    'regime.title': 'Das Regime',
    'regime.lede': 'Wo die Wirtschaft gerade steht. Diese Seite gilt für alle gleich und braucht kein Konto.',
    'regime.unavailable': 'Zurzeit ist kein Regime-Stand veröffentlicht.',
    'regime.nothing_personal': 'Hier steht nichts über Sie. Diese Angaben sind für alle dieselben.',
    'regime.source': 'Woher dieser Stand kommt',
    'regime.source_regime': 'Regime',
    'regime.source_scope': 'Raum',
    'regime.source_as_of': 'Stand',
    'regime.source_model': 'Modellversion',
    'regime.source_published_by': 'Veröffentlicht von',
    'feed.title': 'Beiträge',
    'feed.lede': 'Was zu lesen ist. Tippen Sie ein Thema an, und es wird zu Ihrer Lage — gefragt wird nur, was noch fehlt.',
    'feed.section_groups': 'Gruppen',
    'feed.section_follows': 'Wem Sie folgen',
    'feed.section_vaults': 'Sammlungen',
    'feed.empty_no_gathering_is_seeded': 'Hier steht noch nichts: es ist kein Vortrag und kein Treffen erfasst.',
    'feed.empty_no_follow_relation_exists': 'Hier steht noch nichts: Folgen gibt es in diesem Stand noch nicht.',
    'feed.empty_for_you': 'Für Sie ist hier nichts erfasst.',
    'feed.tap_asks': 'Auf meine Lage beziehen',
    'feed.tap_ready': 'Auf meine Lage beziehen — alles da',
    'feed.ordering_note': 'Reihenfolge wie im Inhaltsverzeichnis. Was Sie gelesen haben, wird nicht erfasst.',
    'network.title': 'Das Netzwerk',
    'network.lede': 'Wer erreichbar ist, und wer vorgeschlagen wäre. Zwei getrennte Ringe.',
    'network.connected': 'Erreichbar',
    'network.connected_empty': 'Zurzeit ist niemand hinterlegt.',
    'network.suggested': 'Vorgeschlagen',
    'network.suggested_empty': 'Hier steht noch niemand: es gibt keine Zuordnung, die Vorschläge berechnen würde. Erfunden wird hier nichts.',
    'network.role_unstated': 'Rolle nicht angegeben',
    'network.privacy': 'Vermögen, Verbindlichkeiten und Ziele werden hier nie sichtbar. In diese Seite fliesst nichts aus Ihrem Vault ein.',
    'nav.regime': 'Regime',
    'nav.feed': 'Beiträge',
    'nav.actions': 'Aufgaben',
    'nav.documents': 'Unterlagen',
    'nav.befund': 'Befund',
    // `door.know_title` und `door.know_body` sind entfernt: hinter der Tür «Wissen & Gemeinschaft» steht
    // jetzt S-10 statt eines Platzhalters. Der Satz, den der Platzhalter zu sagen hatte — das Wissenspanel
    // ist etwas anderes und begleitet jeden Bildschirm — steht als `capabilities.know_panel_note` auf dem
    // wirklichen Bildschirm, wo er mehr nützt.
    // `door.market_title` and `door.market_body` are gone with `renderPlaceholder`. The body string read
    // "Angebote werden nach den vier Rollen geordnet, nicht nach Beruf. Noch nicht gebaut." — its first
    // sentence is R-200 and now stands on the real screen as `market.lede`, beside the filter that
    // implements it; its second was the whole defect.
    'know.panel': 'Das Wissen',
    'know.open': 'Das Wissen öffnen',
    'know.close': 'Schliessen',
    'know.lede': 'Antworten stammen aus Ihren eigenen Unterlagen und aus dem Lernmaterial. Was dort nicht steht, steht auch hier nicht.',
    'know.ask': 'Ihre Frage',
    'know.ask_submit': 'Fragen',
    'know.asking': 'Wird gelesen …',
    'know.answer': 'Antwort',
    'know.unavailable': 'Zurzeit keine Antwort',
    'know.model': 'Modell',
    'know.citations': 'Gestützt auf',
    'know.citation_vault_item': 'Aus Ihrer Ablage',
    'know.citation_learning_unit': 'Aus dem Lernmaterial',
    'know.citation_book_passage': 'Aus dem Buchtext',
    'know.citation_knowledge_entry': 'Aus einem geprüften Merkblatt',
    'know.citation_member_record': 'Aus Ihren eigenen Angaben',
    'know.citation_computation': 'Berechnet aus Ihren Angaben',
    'know.citation_where': 'Fundstelle',
    'know.citation_sources': 'Quellen dieses Merkblatts',
    'know.no_citations': 'Ohne Beleg aus Ihren Unterlagen.',
    'know.boundary': 'Das beantwortet eigentliCH nicht',
    'know.boundary_hint': 'Das ist keine Störung und kein Fehler. Eine Empfehlung für Ihre eigene Lage darf hier nicht entstehen. Eine Kuratorin oder ein Kurator darf sie mit Ihnen besprechen.',
    'know.curator': 'Kuratorin oder Kurator einschalten',
    'know.curator_choose': 'Wen möchten Sie einschalten?',
    'know.curator_loading': 'Wird geholt …',
    'know.curator_person': 'Ihre Anfrage geht an',
    'know.curator_directory_error': 'Wer zurzeit da ist, lässt sich gerade nicht abrufen. Es wird niemand angenommen, also wird nichts gesendet.',
    'know.curator_opened': 'Erfasst, zusammen mit dem Bildschirm, von dem aus Sie gefragt haben.',
    'know.curator_from': 'Geöffnet von',
    'know.curator_unnamed': 'Zurzeit ist keine Kuratorin und kein Kurator benannt, also wird nichts gesendet. Ein Eintrag ohne benannte Person wäre eine Unwahrheit in einem Protokoll, das nur deshalb etwas taugt, weil es wahr ist.',
    'know.actions': 'Vorbereitete Entscheide',
    'know.actions_hint': 'Diese Liste erscheint, wenn Sie das Feld öffnen. Sie meldet sich nie von selbst.',
    'know.actions_empty': 'Zurzeit liegt nichts an.',
    'know.action_due': 'Frist',
    'know.action_no_due': 'Ohne Frist',
    'know.action_options': 'Was zur Wahl steht, und was daraus folgt:',
    'ask.label': 'Ihre Frage',
    'ask.placeholder': 'Fragen Sie etwas über Geld, Vorsorge oder Ihre eigene Lage.',
    'ask.submit': 'Fragen',
    'ask.asking': 'Die Frage läuft.',
    'ask.answered': 'Die Antwort steht.',
    'ask.failed': 'Die Frage konnte nicht gestellt werden.',
    'ask.sources': 'Quellen',
    'ask.source_unnamed': 'Ohne Titel',
    'ask.to_curator': 'Mit einer Kuratorin oder einem Kurator sprechen',
    'ask.start_there': 'Dort beginnen',
    'ask.caveat': 'Woher diese Antwort kommt',
    'ask.caveat_branch': 'Art der Frage',
    'ask.caveat_boundary': 'Bereich',
    'ask.caveat_model': 'Modell',
    'ask.branch_population_fact': 'Eine Frage über die Sache selbst. Ihre Angaben wurden dafür nicht gelesen.',
    'ask.branch_member_situation': 'Eine Frage über Ihre eigene Lage. Dafür wurden Ihre Angaben gelesen.',
    'ask.branch_regulated_advice': 'Eine Frage danach, was zu tun ist. Die beantwortet hier ein Mensch.',
    'ask.boundary_below_both': 'Ohne Personenbezug.',
    'ask.boundary_per_member_computation': 'Mit Ihren eigenen Angaben gerechnet.',
    'ask.boundary_regulated_advice': 'Empfehlung — nur über einen Menschen.',
    'know.action_source': 'Betrifft eine Unterlage in Ihrer Ablage.',
    'know.trigger_vault_expiry': 'Eine Unterlage läuft ab',
    'know.trigger_plan_goal_unfunded': 'Einem Ziel ist keine Position zugeordnet',
    'know.trigger_plan_goal_target_date_passed': 'Das Datum eines Ziels liegt zurück',
    'know.trigger_plan_position_unrevised': 'Eine Position steht lange unverändert',
    'know.trigger_plan_capital_type_empty': 'Eine Kapitalart ist leer',
    'know.trigger_plan_onboarding_answer_skipped': 'Eine Frage aus dem Erstgespräch ist offen',
    'know.trigger_plan_household_confirmation_due': 'Ihr Haushalt ist seit über einem Jahr nicht bestätigt',
    'know.trigger_plan_household_change_inferred': 'Ein Hinweis deutet auf eine Änderung im Haushalt',
    'know.trigger_plan_goal_frozen_for_division': 'Ein gemeinsames Ziel ist zur Aufteilung eingefroren',
    'know.about_goal': 'Betrifft das Ziel',
    'know.about_position': 'Betrifft die Position',
    'know.about_capital': 'Betrifft die Spalte',
    'know.about_question': 'Betrifft die Frage',
    'know.about_household': 'Betrifft Ihren Haushalt',
    'know.about_signal': 'Ausgelöst durch',
    // The signals `client/content/household-confirmation.json` publishes. Named in words rather than
    // shown as a key, because "why am I being asked this?" is the first thing a flag provokes and an
    // identifier is not an answer to it.
    'know.signal_partner_invited': 'eine zweite Person hat Zugang zum Plan erhalten',
    'know.signal_partner_removed': 'der Zugang einer zweiten Person wurde aufgehoben',
    'know.signal_goal_owner_changed': 'die Zuordnung eines Ziels hat sich geändert',
    'know.signal_salary_step_change': 'ein Einkommen hat sich sprunghaft verändert',
    'know.signal_dated_obligation_added': 'eine neue Verpflichtung mit Datum ist erfasst',
    'know.about_unnamed':
      'Der Eintrag, auf den sich dies bezieht, liess sich in Ihrem Plan nicht auffinden. Der Bezug wird '
      + 'deshalb nicht benannt.',
    'know.error': 'Die Frage konnte nicht gestellt werden.',
    'vault.eyebrow': 'Ablage',
    'vault.title': 'Ihre Unterlagen',
    'vault.lede': 'Was Sie hier ablegen, gehört Ihnen. Eine Notiz zählt gleich viel wie ein Vertrag, und nichts wird überschrieben: eine neue Fassung ist eine neue Zeile.',
    'vault.empty': 'Hier liegt noch nichts. Eine Police, ein Vertrag, eine Abmachung in der Familie oder eine Notiz an sich selbst gehören alle hierher.',
    'vault.version': 'Fassung',
    'vault.supersedes': 'ersetzt eine frühere Fassung',
    'vault.expiry': 'Läuft ab am',
    'vault.no_expiry': 'Ohne Ablaufdatum',
    'vault.has_content': 'mit Datei',
    'vault.note_only': 'ohne Datei, als Notiz erfasst',
    'vault.fields': 'Angaben zu dieser Unterlage',
    'vault.provenance_member': 'Von Ihnen angegeben',
    'vault.provenance_extraction': 'Aus der Datei gelesen',
    'vault.confidence': 'Sicherheit der Lesung',
    'vault.disagreement': 'Die Lesung kommt zu einem anderen Wert. Ihre Angabe gilt; beide stehen hier.',
    'vault.kind_policy': 'Police',
    'vault.kind_statement': 'Abrechnung',
    'vault.kind_contract': 'Vertrag',
    'vault.kind_note': 'Notiz',
    'vault.kind_arrangement': 'Abmachung',
    'vault.kind_learning': 'Lernen',
    'vault.kind_other': 'Anderes',
    'vault.source_upload': 'Hochgeladen',
    'vault.source_capture': 'Mit der Kamera erfasst',
    'vault.source_manual': 'Von Hand erfasst',
    'vault.source_forward': 'Weiterleitungsadresse',
    'vault.source_import': 'Übernahme von anderswo',
    'vault.intake_unavailable': 'noch nicht gebaut',
    'vault.intake_note': 'Vier Wege, eine Oberfläche. Zwei davon sind noch nicht gebaut. Sie stehen hier trotzdem, damit Sie sehen, was es noch nicht gibt.',
    'vault.add_title': 'Etwas ablegen',
    'vault.add_name': 'Titel',
    'vault.add_kind': 'Art',
    'vault.add_kind_hint': 'Eine Notiz und eine Abmachung stehen gleichberechtigt neben einer Police.',
    'vault.add_file': 'Datei (optional)',
    'vault.add_file_hint': 'Ohne Datei ist es eine Notiz, und eine Notiz ist eine vollwertige Ablage.',
    'vault.add_notes': 'Text (optional)',
    'vault.add_notes_hint': 'Was Sie selbst festhalten möchten. Bei einer Notiz ist das der Inhalt.',
    'vault.add_expiry': 'Ablaufdatum (optional)',
    'vault.add_expiry_hint': 'Ein Ablaufdatum wird zu einem vorbereiteten Entscheid im Wissen.',
    'vault.add_more': 'Weg der Erfassung und frühere Fassung',
    'vault.add_source': 'Wie kommt es herein?',
    'vault.add_supersedes': 'Ersetzt',
    'vault.add_supersedes_hint': 'Die frühere Fassung bleibt bestehen und bleibt im Export.',
    'vault.supersedes_none': 'Nichts, es ist neu',
    'vault.save': 'Ablegen',
    'vault.export_label': 'Alles, was Ihnen gehört',
    'vault.export': 'Vollständigen Export herunterladen',
    'vault.export_hint': 'In einem dokumentierten Format, ohne Rückfrage bei irgendjemandem.',
    'vault.export_ready': 'Die Datei ist bereit.',
    'containers.eyebrow': 'Plan',
    'containers.title': 'Wofür das Geld da ist',
    'containers.lede': 'Ziele teilen Ihr Vermögen nicht auf. Dieselbe Position kann mehrere Ziele tragen, und wo das so ist, steht es dabei. Es sind keine getrennten Konten.',
    'containers.empty': 'Noch kein Ziel benannt. Ein Ziel ist eine Absicht, kein Konto.',
    'containers.parameters': 'Die fünf Angaben',
    'containers.param_safety': 'Sicherheit',
    'containers.param_liquidity_need': 'Wie schnell verfügbar',
    'containers.param_volatility_tolerance': 'Erträgliche Schwankung',
    'containers.param_horizon': 'Zeitraum',
    'containers.param_flexibility': 'Beweglichkeit',
    'containers.param_unanswered': 'nicht beantwortet',
    'containers.param_hint': 'In Ihren eigenen Worten. Diese fünf werden gespeichert und heute nicht ausgewertet.',
    // The unit is in the label, because a bare "Betrag" is what the owner asked "in welcher Frequenz?"
    // about on the position form. A goal's target is one sum in francs, not a rate — the field says so.
    'containers.target_amount': 'Zielbetrag in CHF',
    'containers.target_amount_hint': 'Ein einmaliger Betrag, nicht pro Jahr. Leer lassen, wenn kein Betrag passt — ein Ziel ohne Betrag ist ein vollwertiges Ziel.',
    'containers.target_date': 'Zieldatum',
    'containers.no_target_date': 'Ohne Datum',
    'containers.funding': 'Getragen von',
    'containers.unfunded': 'Keine Position benennt dieses Ziel. Das ist ein zulässiger Zustand.',
    // ---- the occupancy question and the property finding (client/surfaces/containers.js)
    // The three option labels are NOT here: they travel on the goal payload from
    // `property-funding.json`, because the set of occupancies is a published convention and a second
    // copy of it in this table would be the R-154 shape.
    'containers.property': 'Wohneigentum: was die Prüfung sagt',
    'containers.property_verdict_meets': 'Nach den veröffentlichten Regelsätzen ist dieses Ziel finanzierbar.',
    'containers.property_verdict_does_not_meet': 'Nach den veröffentlichten Regelsätzen ist dieses Ziel so nicht finanzierbar.',
    'containers.property_verdict_could_not_be_determined': 'Dazu lässt sich noch nichts sagen. Was fehlt, steht darunter.',
    'containers.property_question': 'Wohnen Sie selbst darin?',
    'containers.property_question_hint': 'Wohnen Sie selbst darin? Das entscheidet, wie viel Eigenmittel verlangt werden und ob Vorsorgekapital überhaupt eingesetzt werden darf. Aus dem Namen des Ziels lässt es sich nicht ableiten, und Raten wäre hier teurer als Fragen.',
    'containers.property_your_answer': 'Ihre Antwort',
    'containers.property_clear': 'Die Frage offen lassen',
    'containers.property_recorded': 'Antwort festgehalten.',
    'containers.property_failed': 'Die Antwort konnte nicht festgehalten werden.',
    'containers.property_binds': 'Entschieden hat',
    'containers.property_test_equity': 'die Eigenmittel',
    'containers.property_test_affordability': 'die Tragbarkeit',
    'containers.property_because_the_goal_does_not_say_whether_the_member_will_live_in_it': 'Es ist nicht festgehalten, ob Sie selbst darin wohnen.',
    'containers.property_because_the_goal_names_no_amount': 'Das Ziel nennt keinen Betrag.',
    'containers.property_because_no_position_is_linked_to_this_goal': 'Keine erfasste Position ist als Deckung dieses Ziels hinterlegt. Ohne das lässt sich nicht sagen, welches Geld für den Kauf zur Verfügung steht.',
    'containers.property_because_no_income_is_recorded_for_the_household': 'Für Ihren Haushalt ist kein Einkommen erfasst, und die Tragbarkeit rechnet gegen das Haushaltseinkommen.',
    'containers.property_because_the_goal_names_an_occupancy_the_record_does_not_declare': 'Die festgehaltene Nutzungsart steht nicht im veröffentlichten Regelsatz.',
    'containers.property_because_rental_income_is_not_modelled_for_a_let_property': 'Zur Tragbarkeit sagt dieses Ergebnis nichts, und das ist eine Entscheidung: bei einem vermieteten Objekt trägt die Miete den grössten Teil der Kosten, und wie stark eine Bank eine erwartete Miete kürzt, bevor sie sie anrechnet, ist nirgends veröffentlicht. Eine Zahl an dieser Stelle wäre geraten.',
    'containers.property_because_the_property_conventions_are_not_approved': 'Der Regelsatz für Eigenmittel und Tragbarkeit ist nicht freigegeben, also wird daraus nichts gerechnet.',
    'containers.overlap_note': 'Diese Positionen gehören nicht diesem Ziel. Sie tragen es.',
    'containers.also_carries_one': 'Diese Position trägt auch ein weiteres Ziel.',
    'containers.also_carries_many': 'Diese Position trägt auch {n} weitere Ziele.',
    'containers.liquidity_immediate': 'Sofort verfügbar',
    'containers.liquidity_within_months': 'Innert Monaten verfügbar',
    'containers.liquidity_within_years': 'Innert Jahren verfügbar',
    'containers.liquidity_illiquid': 'Nicht verlässlich verfügbar',
    'containers.liquidity_unstated': 'Verfügbarkeit nicht angegeben',
    'containers.observations': 'Was dazu zutrifft',
    'containers.obs_dated_but_unfunded': 'Dieses Ziel hat ein Datum ({date}) und keine Position, die es trägt.',
    'containers.obs_dated_but_funding_is_illiquid': 'Dieses Ziel hat ein Datum ({date}). Alles, was es trägt, haben Sie als nicht verlässlich verfügbar angegeben.',
    'containers.obs_liquidity_not_stated': 'Bei einer tragenden Position ist nicht angegeben, wie schnell sie verfügbar ist. Ohne diese Angabe lässt sich nichts vergleichen.',
    'containers.obs_funding_shared_with_other_goals': 'Eine tragende Position trägt auch andere Ziele.',
    'containers.illustration_none': 'Keine Hochrechnung.',
    'containers.illustration_no_assumption_set_published': 'Es ist kein Annahmesatz veröffentlicht, und eine Hochrechnung ohne veröffentlichte Annahmen wäre eine Behauptung.',
    'containers.add_title': 'Ziel benennen',
    'containers.name': 'Name',
    'containers.template': 'Vorlage',
    'containers.template_unnamed': 'Ohne Vorlage',
    // The placeholder in a template select. It exists so that nothing is chosen for the member: with nine
    // templates in the list, whichever one happens to be first would otherwise be assigned to every goal
    // by a member who never opened the control.
    'containers.template_choose': 'Bitte auswählen',
    'containers.template_purpose': 'Was diese Vorlage bedeutet',
    'containers.funding_select': 'Welche Positionen tragen es?',
    'containers.funding_hint': 'Mehrere sind möglich, und dieselbe Position darf auch andere Ziele tragen.',
    'containers.no_positions': 'Sie haben noch keine Position erfasst, die ein Ziel tragen könnte.',
    'containers.save': 'Ziel erfassen',
    'containers.default_question': 'Ziel {name} erfassen?',
    // ---- changing a goal after it is named ----
    //
    // "Ändern", not "Berichtigen": R-162's "record a correction, never edit" is a statement about a
    // Decision, which cannot be rewritten. A goal is an intention and it may genuinely change — the member
    // has not made a mistake by wanting a different date. What is append-only is the record beneath it, and
    // `containers.edit_lede` is where that is said instead of being hidden behind a verb.
    'containers.edit': 'Ziel ändern',
    'containers.edit_title': 'Ziel ändern',
    'containers.edit_lede': 'Was Sie ändern, wird als Entscheid festgehalten — zusammen mit dem, was bisher galt. Der frühere Entscheid bleibt bestehen und wird nicht überschrieben.',
    'containers.edit_save': 'Änderung festhalten',
    'containers.edit_cancel': 'Abbrechen',
    'containers.edit_unchanged': 'Es ist nichts geändert. Ändern Sie eine Angabe, oder brechen Sie ab.',
    'containers.edit_default_question': 'Ziel {name} ändern?',
    'containers.edit_done': 'Die Änderung ist festgehalten.',
    'containers.edit_clear_hint': 'Ein Feld leer lassen heisst hier: die Angabe wird entfernt.',

    // ---- R-133 / C-02: the illustration, when there IS one ----
    //
    // Until 31 August 2026 there was exactly one reason string here — `no_assumption_set_published` — and
    // `containers.js` printed `illustration_none` plus that reason unconditionally. Two things were wrong
    // at once: a goal with an amount and active funding returns a real illustration and the screen said
    // "no projection" over the top of it, and the five other reasons had no string at all, so a goal
    // without an amount showed a member the key `containers.illustration_the_goal_names_no_amount`.
    //
    // All six reasons are written out below, and the illustration itself is rendered. **The rate's horizon
    // and the goal's horizon are two different numbers and both are stated**, because the published set
    // estimates one year and nothing extends it — rendering the goal's date beside a one-year range without
    // saying so would be C-02's violation dressed as a courtesy.
    'containers.illustration_no_assumption_set_in_effect_yet': 'Es ist ein Annahmesatz veröffentlicht, aber keiner gilt ab heute.',
    'containers.illustration_the_assumption_set_publishes_no_role_profiles': 'Der veröffentlichte Annahmesatz enthält keine Sätze je Rolle, und ohne die gibt es nichts zu illustrieren.',
    'containers.illustration_the_goal_names_no_amount': 'Dieses Ziel nennt keinen Betrag, und eine Illustration braucht den Betrag, auf den sie sich bezieht.',
    'containers.illustration_the_goal_names_no_active_funding': 'Keine aktive Position trägt dieses Ziel, deshalb gibt es keine Rolle, für die ein Satz gelesen werden könnte.',
    'containers.illustration_the_funding_roles_are_not_in_the_assumption_set': 'Der veröffentlichte Annahmesatz enthält keine Sätze für die Rollen, die dieses Ziel tragen.',
    // Grundsatz 9. Dieses Ziel IST getragen — der Unterschied zu «keine aktive Position» ist der ganze
    // Punkt der eigenen Begründung: der Eintrag ist vollständig, und es ist die Rechnung, die aussetzt.
    'containers.illustration_the_goal_is_funded_only_by_human_capital':
      'Dieses Ziel wird bisher nur durch Ihre Arbeitskraft finanziert. Für Arbeitskraft veröffentlicht '
      + 'der Annahmesatz keine Marktrendite, deshalb steht hier keine Zahl. Am Eintrag fehlt nichts.',
    // A129. Der genannte Betrag ist der Kaufpreis, und der Kaufpreis ist nicht der Betrag, der
    // angespart werden muss — das sind die Eigenmittel, also etwa ein Fünftel davon. Eine Hochrechnung
    // auf den Kaufpreis würde am fünffachen Betrag gemessen.
    'containers.illustration_the_goal_is_a_property_purchase':
      'Bei einem Immobilienkauf ist der genannte Betrag der Kaufpreis. Angespart werden müssen die '
      + 'Eigenmittel — ein Teil davon. Eine Hochrechnung auf den Kaufpreis würde am falschen Betrag '
      + 'messen, deshalb steht hier keine Zahl.',
    'containers.excluded_heading': 'Nicht eingerechnet',
    'containers.excluded_human_capital_carries_no_market_rate':
      'Arbeitskraft trägt keine Marktrendite. Die Position bleibt erfasst und wird nicht mit null '
      + 'gerechnet — null wäre die Behauptung, ein Lohn bewege sich erwartungsgemäss nicht.',
    'containers.illustration_projected_on': 'Gerechnet wurde auf',
    'containers.illustration_heading': 'Illustration',
    'containers.illustration_lede': 'Das ist eine Illustration und keine Prognose. Sie zeigt, was die veröffentlichten Sätze für den Betrag bedeuten, den Sie genannt haben — je Rolle und je Szenario, einzeln.',
    'containers.illustration_basis': 'Bezugsbetrag',
    'containers.illustration_basis_note': 'Das ist der Betrag, den Sie für dieses Ziel genannt haben. Es ist kein Bestand: was Sie besitzen, hält der Plan nicht als Frankenbetrag fest.',
    'containers.illustration_assumption_set': 'Annahmesatz',
    'containers.illustration_effective_from': 'Gültig ab',
    'containers.illustration_published_by': 'Veröffentlicht von',
    'containers.illustration_horizon': 'Zeitraum',
    'containers.illustration_horizon_one_year': 'Die veröffentlichten Sätze sind für ein Jahr geschätzt.',
    'containers.illustration_horizon_years': 'Die veröffentlichten Sätze sind für {years} Jahre geschätzt.',
    'containers.illustration_goal_horizon': 'Ihr Zieldatum liegt {years} Jahre entfernt.',
    'containers.illustration_not_extended': 'Die Sätze sind nicht auf Ihr Zieldatum verlängert. Ein Satz für ein Jahr ist nicht derselbe Satz, über mehrere Jahre fortgeschrieben — eigentliCH schreibt ihn nicht fort.',
    'containers.illustration_no_goal_date': 'Dieses Ziel nennt kein Datum, deshalb steht dem Zeitraum der Sätze kein Zielzeitraum gegenüber.',
    'containers.illustration_unit_annualised_decimal': 'Die Sätze sind Jahreswerte.',
    'containers.illustration_role': 'Rolle',
    'containers.illustration_set_role': 'Im Annahmesatz heisst diese Rolle {name}.',
    'containers.illustration_one_position_names_role': 'Eine Position, die dieses Ziel trägt, hat diese Rolle.',
    'containers.illustration_n_positions_name_role': 'Positionen mit dieser Rolle, die dieses Ziel tragen: {n}.',
    'containers.illustration_scenario': 'Szenario',
    'containers.illustration_rate': 'Satz',
    'containers.illustration_change': 'Veränderung in CHF',
    'containers.illustration_after': 'Danach in CHF',
    'containers.illustration_probability': 'Veröffentlichte Wahrscheinlichkeit',
    // A69, said on the screen and not only in the service. The probabilities travel beside the rates and
    // nothing multiplies them, so nothing here shows a weighted average — which is what a member would
    // read as "the" number and is precisely the decision the owner reserved.
    'containers.illustration_probability_note': 'Die Wahrscheinlichkeiten stehen neben den Sätzen, so wie sie veröffentlicht sind. Sie werden nicht mit ihnen verrechnet: welche Wahrscheinlichkeit welchen Zeitraum gewichtet, ist eine Entscheidung mit einer verantwortlichen Person, und ein Mittelwert auf dieser Seite würde sie verdecken.',
    'containers.illustration_probability_unstated': 'nicht veröffentlicht',
    'containers.scenario_crisis': 'Krise',
    'containers.scenario_contraction': 'Abschwung',
    'containers.scenario_stagnation': 'Stagnation',
    'containers.scenario_expansion': 'Aufschwung',
    'containers.scenario_boom': 'Hochkonjunktur',
    'containers.illustration_caveats': 'Was dabei gilt',
    'containers.caveat_rates_hold_at_the_published_horizon_only': 'Die Sätze gelten für den Zeitraum, für den sie geschätzt wurden, und für keinen anderen.',
    'containers.caveat_no_blended_rate_is_published': 'Es ist kein gemischter Satz veröffentlicht. Was hier steht, ist je Rolle und je Szenario getrennt.',
    'containers.caveat_not_in_real_terms_because_no_inflation_is_published': 'Es ist keine Teuerung veröffentlicht, deshalb ist hier nichts in heutiger Kaufkraft gerechnet.',
    'containers.caveat_the_amount_is_stated_by_the_member_and_is_not_a_holding': 'Der Betrag ist der, den Sie genannt haben. Er ist kein Bestand.',
    'containers.caveat_an_illustration_and_not_a_forecast': 'Das ist eine Illustration und keine Prognose.',
    'containers.illustration_no_trajectory': 'Warum hier kein Verlauf über die Jahre steht',
    'containers.illustration_no_trajectory_lede': 'Ein Verlauf über die Jahre bräuchte Angaben, die nicht vorliegen:',

    // ---- what an engine wants and a plan does not hold ----
    //
    // **One family, used by two surfaces**, because it is one vocabulary: `AbsentInput.kind` and the engine
    // input names come out of `services/engine_inputs.py`, and the illustration's "why there is no
    // trajectory" list and the run surface's refusal are two views of the same gaps. Two key families would
    // be the same sentence in two places, edited on one side.
    //
    // **The subjects are the Befund's, deliberately word for word.** `services/befund.py::GAP_SUBJECTS`
    // maps each engine input to the thing a member would recognise, and a member who reads
    // "Ihr Humankapital als Betrag in Franken" in the report and something else on the run screen has been
    // handed two names for one absence.
    //
    // **`AbsentInput.reason` is NOT rendered anywhere.** It is the considered sentence in the mapping layer
    // and it exists in English only — a note to whoever reads that module. A12 makes member copy bilingual,
    // and putting an English paragraph on a German screen is precisely the half-translated product A12
    // exists to prevent. The Befund makes the same choice for the same reason: it maps the gap to a subject
    // and composes its own sentence in both languages rather than forwarding the note.
    'gap.input_W_L': 'Ihr Humankapital als Betrag in Franken',
    'gap.input_W_R': 'Ihr Finanzvermögen als Betrag in Franken',
    'gap.input_initial_wealth': 'Ihr Finanzvermögen als Betrag in Franken',
    'gap.input_D': 'Ihre Schulden',
    'gap.input_E': 'eine Grösse aus dem Rechenmodell, für die es in Ihrem Plan keine Entsprechung gibt',
    'gap.input_annual_return': 'eine Rendite als einzelne Zahl',
    'gap.input_base_snapshot_id': 'ein numerierter Ausgangsstand Ihres Plans',
    // The `supplied_by_the_caller` half. These are parameters of a *request* rather than holes in a plan,
    // and `services/runs.py` refuses rather than inventing one — "inventing one here would be this layer
    // deciding what the member wanted to try". Two of them are filled by naming a goal on the run screen,
    // which is what the optional goal select is for.
    'gap.input_regime_id': 'die Marktlage, auf die sich diese Schätzung beziehen soll',
    'gap.input_horizon_years': 'über welchen Zeitraum gerechnet werden soll — ein Ziel mit Datum sagt das',
    'gap.input_target': 'der Betrag, auf den hin gerechnet werden soll — ein Ziel mit Betrag sagt das',
    'gap.input_field': 'was in der Frage «was wäre wenn» geändert werden soll',
    'gap.input_to_value': 'worauf es geändert werden soll',
    'gap.kind_not_in_the_plan': 'das hält Ihr Plan nicht fest',
    'gap.kind_needs_an_unpublished_assumption': 'dafür braucht es eine Annahme, die eigentliCH veröffentlicht hat',
    'gap.kind_supplied_by_the_caller': 'das gehört zur Anfrage und nicht zum Plan',

    // ---- the Befund: the standing report a member can read ----
    //
    // The owner, twice: "I can put all the information in but I don't get anything out of it, like an
    // action plan, like a status update, report or whatever" — and then, after the report had been built
    // behind the API, "there is still no output". This is the copy of the screen that renders it.
    //
    // **The section titles are NOT here.** `services/befund.py` composes them in both languages and ships
    // them in the payload, because the order and the wording are editorial decisions belonging to the
    // report rather than interface furniture. The same is true of every sentence in it. What is here is the
    // chrome around them, and the labels for the member's own words, which travel separately from the
    // composed sentences and are rendered as quotations.
    //
    // R-113 / C-07: there is no key here for a count of sections, a count of facts, or how much of the
    // report is filled in — the payload carries none of those numbers and this table has no word for one.
    'befund.eyebrow': 'Befund',
    'befund.title': 'Ihr Befund',
    'befund.lede': 'Dieser Befund hält fest, was Sie erfasst haben, und was daraus folgt. Er rechnet nichts fort, und er bewertet nichts.',
    'befund.on_request': 'Er entsteht in dem Moment, in dem Sie ihn öffnen. Er wird nicht verschickt, nicht gemeldet und nicht im Hintergrund erzeugt.',
    'befund.as_of': 'Stand',
    'befund.print': 'Drucken',
    'befund.announced': 'Der Befund ist geladen.',
    'befund.assumptions': 'Annahmen',
    'befund.assumption_set': 'Annahmesatz',
    'befund.empty_section': 'In diesem Abschnitt steht heute nichts.',
    'befund.model_wrote': 'Diesen Satz hat das Sprachmodell umformuliert.',
    'befund.computed_sentence': 'Berechneter Satz',
    // The labels on the member's own words. `Fact.quoted` holds what the member wrote and `Fact.subject`
    // names which key belongs in front of the sentence; both are rendered as quotations and never spliced
    // into a composed sentence, so a member's own wording cannot change what eigentliCH is saying.
    'befund.quoted_goal_name': 'Ziel',
    'befund.quoted_position_labels': 'Positionen',
    'befund.quoted_question': 'Frage',
    'befund.quoted_choice': 'Entscheid',
    'befund.quoted_reasoning': 'Begründung',
    'befund.quoted_title': 'Dokument',
    'befund.quoted_prepared_options': 'Möglichkeiten und ihre Folgen',

    // ---- R-301: asking for an engine run, and waiting honestly ----
    'nav.runs': 'Berechnungen',
    'runs.eyebrow': 'Plan',
    'runs.title': 'Eine Berechnung anfordern',
    'runs.lede': 'Ein Rechenmodell liest, was Ihr Plan festhält, und rechnet daraus etwas aus. Sie geben dafür nichts ein: die Eingaben stammen aus Ihren erfassten Positionen und Zielen. Am Plan ändert eine Berechnung nichts.',
    // The half-hour is not a hypothetical: `market_signal` declares 1800 seconds. A screen that polls for
    // half an hour without saying anything is a screen that looks broken.
    'runs.lede_wait': 'Ein Modell darf lange laufen — eines davon bis zu einer halben Stunde. Diese Seite fragt in Abständen nach und sagt, solange es noch läuft.',
    'runs.engine': 'Rechenmodell',
    'runs.engine_choose': 'Bitte auswählen',
    'runs.engine_market_signal': 'Marktlage',
    'runs.engine_return_estimation': 'Renditeschätzung',
    'runs.engine_s_curve_trajectory': 'Verlauf über die Jahre',
    'runs.engine_life_balance_sheet': 'Lebensbilanz',
    'runs.engine_scenario_generator': 'Was wäre wenn',
    'runs.goal': 'Zu welchem Ziel? Freiwillig.',
    'runs.goal_none': 'Zu keinem bestimmten Ziel',
    'runs.submit': 'Berechnung anfordern',
    'runs.list_heading': 'Angeforderte Berechnungen',
    'runs.none_yet': 'Sie haben noch keine Berechnung angefordert. Hier stünde jede, die Sie angefordert haben, mit dem, was zurückkam.',
    'runs.announced': 'Die Berechnungen sind geladen.',
    'runs.status_submitted': 'Eingereicht',
    'runs.status_running': 'Läuft',
    'runs.status_done': 'Fertig',
    'runs.status_failed': 'Nicht verfügbar',
    'runs.submitted_at': 'Angefordert',
    'runs.started_at': 'Begonnen',
    'runs.finished_at': 'Beendet',
    // Stated as its own sentence, deliberately apart from the clock below it. The declared budget and the
    // time a run has been going are not shown as a pair: a pair is one division away from a completion
    // meter, and C-07 has no room for one.
    'runs.budget_minutes': 'Für dieses Modell sind bis zu {minutes} Minuten vorgesehen.',
    'runs.budget_seconds': 'Für dieses Modell sind bis zu {seconds} Sekunden vorgesehen.',
    'runs.still_working': 'Läuft noch. Diese Seite fragt weiter nach.',
    'runs.elapsed': 'Unterwegs seit {clock}.',
    'runs.last_checked': 'Zuletzt nachgefragt um {time}.',
    'runs.check_failed': 'Die letzte Nachfrage kam nicht durch. Diese Seite versucht es weiter.',
    'runs.took': 'Gelaufen ist es {seconds} Sekunden.',
    'runs.result_heading': 'Was zurückkam',
    'runs.unavailable_lede': 'Dieses Modell hat keine Antwort geliefert. Es steht keine Zahl dabei — eine Zahl aus einem Lauf, der nicht durchgelaufen ist, wäre keine Messung.',
    'runs.reason': 'Grund',
    'runs.refused_heading': 'Diese Berechnung ist nicht angefordert worden',
    'runs.refused_the_plan_does_not_answer_this_engine': 'Ihr Plan hält nicht fest, was dieses Modell braucht.',
    'runs.refused_requires_an_input_the_member_did_not_supply': 'Dieses Modell braucht eine Angabe, die zu einer Anfrage gehört und nicht im Plan steht.',
    'runs.refused_requires_a_curator': 'Dieses Modell ordnet Anlageprodukte. Das ist keine Auskunft, die eigentliCH Ihnen erteilt.',
    'runs.refused_unknown_engine': 'Ein Modell mit diesem Namen gibt es nicht.',
    'runs.gaps_heading': 'Was dafür fehlt',
    'runs.announced_queued': 'Die Berechnung ist angefordert.',
    'runs.announced_running': 'Die Berechnung läuft.',
    'runs.announced_done': 'Die Berechnung ist fertig.',
    'runs.announced_failed': 'Die Berechnung hat keine Antwort geliefert.',
    'runs.announced_refused': 'Die Berechnung ist nicht angefordert worden.',

    // ---- S-07: die Entscheidungen (R-160 bis R-162) ----
    //
    // R-162 steckt in der Sprache: die Schaltfläche heisst «Korrektur festhalten», nie «bearbeiten». Eine
    // Entscheidung wird nicht geändert — es entsteht ein neuer Eintrag, der auf den früheren verweist, und
    // der frühere bleibt unverändert stehen. Wer «bearbeiten» liest, erwartet das Gegenteil.
    //
    // C-07: hier steht keine Zahl von Entscheidungen. S-07 ist genau der Bildschirm, den eine
    // Vollzähligkeitsangabe verderben würde.
    'decisions.eyebrow': 'Protokoll',
    'decisions.title': 'Ihre Entscheidungen',
    'decisions.lede':
      'Jede Änderung an Ihrem Plan steht hier mit der Frage, die sich stellte, und Ihrer Begründung. '
      + 'Diese Einträge bleiben, auch wenn die Begleitung wechselt.',
    'decisions.nav': 'Entscheidungen',
    'decisions.newest_first': 'Neueste zuerst.',
    'decisions.recorded_on': 'Festgehalten am',
    'decisions.author_member': 'Von Ihnen festgehalten.',
    'decisions.author_curator': 'Von einem Kurator festgehalten.',
    'decisions.author_system': 'Von eigentliCH festgehalten.',
    'decisions.curator_involved': 'Dabei war ein Kurator beteiligt.',
    'decisions.curator_ref': 'Kurator',
    'decisions.is_correction': 'Dies ist eine Korrektur eines früheren Eintrags.',
    'decisions.was_corrected': 'Zu diesem Eintrag ist später eine Korrektur festgehalten worden.',
    'decisions.quoted_question': 'Die Frage',
    'decisions.quoted_choice': 'Ihr Entscheid',
    'decisions.quoted_reasoning': 'Ihre Begründung',
    'decisions.quoted_options_considered': 'Erwogene Möglichkeiten',
    'decisions.open': 'Diesen Eintrag ansehen',
    'decisions.back': 'Zurück zur Übersicht',
    'decisions.linked_heading': 'Was dieser Eintrag betrifft',
    'decisions.linked_positions': 'Positionen',
    'decisions.linked_goals': 'Ziele',
    'decisions.linked_vault_items': 'Dokumente',
    // C-04: eine VaultItem-Kennung reist ohne Titel und ohne Art. Das ganze Dokument ist K3, und selbst
    // seine Art hier zu nennen würde diese Antwort von K2 auf K3 heben. Der Befund entscheidet gleich.
    'decisions.vault_item_id_only':
      'Zu Dokumenten steht hier nur die Kennung. Titel und Art gehören zum Dokument selbst und stehen im '
      + 'Dokumentenschrank.',
    'decisions.chain_heading': 'Der Verlauf dieses Eintrags',
    'decisions.chain_oldest_first': 'Ältester Eintrag zuerst.',
    'decisions.chain_this_one': 'Dieser Eintrag',
    'decisions.chain_single': 'Zu diesem Eintrag ist keine Korrektur festgehalten.',
    // R-162, wörtlich. Nie «bearbeiten».
    'decisions.correct': 'Korrektur festhalten',
    'decisions.correct_heading': 'Korrektur festhalten',
    'decisions.correct_hint':
      'Der frühere Eintrag bleibt unverändert stehen. Es entsteht ein neuer Eintrag, der auf ihn '
      + 'verweist. Die Frage bleibt dieselbe — sie gehört zu dem, was damals festgehalten wurde.',
    'decisions.correct_choice': 'Was gilt jetzt?',
    'decisions.correct_reasoning': 'Begründung (optional)',
    'decisions.correct_save': 'Korrektur festhalten',
    'decisions.correct_cancel': 'Abbrechen',
    'decisions.correct_choice_missing': 'Bitte halten Sie fest, was jetzt gilt. Ein leerer Eintrag bliebe leer.',
    'decisions.corrected': 'Die Korrektur ist festgehalten.',
    'decisions.filter_heading': 'Eingeschränkt auf',
    'decisions.filter_position': 'Position',
    'decisions.filter_goal': 'Ziel',
    'decisions.filter_vault_item': 'Dokument',
    'decisions.filter_clear': 'Einschränkung aufheben',
    'decisions.filtered_none':
      'Zu dieser Einschränkung ist kein Eintrag festgehalten. Ohne die Einschränkung stehen die übrigen '
      + 'Einträge weiterhin da.',
    'decisions.announced': 'Die Entscheidungen sind geladen.',
    'decisions.announced_one': 'Der Eintrag ist geladen.',

    // ---- R-103: die Zustimmung bei der Registrierung ----
    //
    // Der Text kommt vollständig vom Server (`GET /api/consent-statement`) und wird hier nicht
    // nachgedichtet. Was hier steht, ist die Umgebung: die Überschrift, die Kästchen, die Weigerung.
    'consent.heading': 'Was eigentliCH mit Ihren Angaben tut',
    'consent.lede':
      'Bevor ein Konto entsteht, steht hier, was mit Ihren Angaben geschieht. Der Wortlaut kommt vom '
      + 'Server und wird hier unverändert angezeigt.',
    'consent.provisional':
      'Dieser Wortlaut ist vorläufig. Es sind ehrliche Beschreibungen dessen, was eigentliCH tut, und keine '
      + 'Datenschutzerklärung — niemand mit der nötigen Qualifikation hat sie geprüft.',
    'consent.agree': 'Ich stimme dem oben stehenden Text zu.',
    'consent.required': 'Ohne diese Zustimmung entsteht kein Konto.',
    // ---- Hinweise: keine Wahl, und deshalb auch kein Kästchen ----
    //
    // `entscheidprotokoll` ist ein Hinweis und keine Zustimmung. Das Festhalten gehört zum Dienst, lässt
    // sich nicht abwählen und der Eintrag lässt sich nachträglich nicht entfernen — deshalb wird es
    // mitgeteilt und nicht zur Wahl gestellt. Hier steht bewusst kein «Ich habe das gelesen»: eine
    // Bestätigung, die nichts festhält, sähe wie eine Wahl aus, die es nicht gibt.
    'consent.notice_kind': 'Hinweis',
    'consent.notice_only':
      'Dies ist ein Hinweis und keine Zustimmung. Es gibt hier nichts anzukreuzen: das Festhalten gehört '
      + 'zum Dienst und lässt sich nicht abwählen, deshalb wird es Ihnen mitgeteilt.',
    // C-07 fing «Punkte» hier ein zweites Mal — dieselbe Verbotsliste, dieselbe Stunde, ein anderer Satz.
    'consent.notices_are_not_a_choice':
      'Nicht alles unten fragt Sie etwas. Einiges davon sind Hinweise: sie werden Ihnen mitgeteilt, weil '
      + 'sie zum Dienst gehören — nicht zur Wahl gestellt, und nicht widerrufbar.',
    'consent.consequence_consent': 'Was ein Widerruf bedeuten würde',
    'consent.consequence_notice': 'Warum das nicht zur Wahl steht',
    'consent.version': 'Fassung',
    // C-07 fing hier ein echtes Wort: der erste Entwurf sagte «den erforderlichen Punkten», und «Punkten»
    // steht auf der Verbotsliste — gefunden vom Filter, nicht beim Lesen (A88).
    'consent.missing':
      'Bitte stimmen Sie dort zu, wo eine Zustimmung erforderlich ist. eigentliCH eröffnet ohne sie kein '
      + 'Konto, und es wird auch keines angelegt.',
    'consent.unavailable':
      'Der Wortlaut konnte nicht geladen werden. Ohne ihn wird das Formular nicht abgeschickt: eine '
      + 'Zustimmung zu einem Text, der nicht angezeigt wurde, wäre keine.',
    'consent.retry': 'Nochmals laden',

    // ---- R-230: Zustimmungen ansehen und widerrufen ----
    'consents.eyebrow': 'Einstellungen',
    'consents.heading': 'Ihre Zustimmungen',
    'consents.lede':
      'Jede Zustimmung, die Sie gegeben haben, mit der Fassung des Wortlauts, der damals angezeigt wurde. '
      + 'Widerrufene bleiben in der Liste.',
    'consents.granted_at': 'Zugestimmt am',
    'consents.withdrawn_at': 'Widerrufen am',
    'consents.standing': 'Gilt.',
    'consents.withdrawn': 'Widerrufen.',
    // Was hier bis zum 1. September 2026 stand, war falsch: «Ohne diese Zustimmung lässt sich das Konto
    // nicht weiterführen.» `withdrawn_at` wird geschrieben und von keiner Stelle gelesen, die etwas
    // freigibt oder sperrt — ein Audit hat jede Route nachgemessen. Der Merker gilt für die Eröffnung und
    // für sonst nichts, und genau das sagt der Satz jetzt. Der Satz bleibt kurz: was ein Widerruf
    // bedeutet, steht ausführlich im `consequence`-Text des Servers auf demselben Bildschirm, und eine
    // zweite, kürzere Fassung davon wäre eine zweite Fassung, die abweichen kann.
    'consents.required':
      'Ohne diese Zustimmung wird kein Konto eröffnet. Auf ein bestehendes Konto wirkt sich ein Widerruf '
      + 'nicht von selbst aus.',
    // Die Beschriftung richtet sich nach `kind`, weil das Feld für beide Arten dasselbe heisst
    // (`consequence`) und für die eine «Widerruf» bedeutet und für die andere «es gibt keinen».
    'consents.consequence_consent': 'Was ein Widerruf bedeutet',
    'consents.consequence_notice': 'Warum das nicht zur Wahl steht',
    // Eine Zeile, die aus der Zeit stammt, als eigentliCH dafür noch um Zustimmung gebeten hat. Sie bleibt
    // sichtbar — R-230 fragt genau danach —, und daneben steht keine Schaltfläche.
    'consents.notice_row':
      'Dazu wird heute nicht mehr um Zustimmung gebeten, sondern informiert. Ihre damalige Zustimmung '
      + 'bleibt sichtbar, und es gibt daran nichts zu widerrufen.',
    'consents.withdraw': 'Widerrufen',
    'consents.withdraw_confirm': 'Widerruf festhalten',
    'consents.withdraw_cancel': 'Abbrechen',
    // Ausgesprochen, weil ein Bildschirm sonst «aus der Liste entfernen» anbieten würde.
    'consents.marks_not_deletes':
      'Ein Widerruf wird vermerkt, er löscht nichts. Der Eintrag bleibt mit dem Datum des Widerrufs '
      + 'stehen.',
    'consents.withdrawn_announced': 'Der Widerruf ist festgehalten.',
    'consents.purpose_datenbearbeitung': 'Bearbeitung Ihrer Angaben',
    'consents.purpose_entscheidprotokoll': 'Protokoll der Entscheidungen',
    'consents.purpose_kuratoren_zugriff': 'Zugriff von Kuratoren',
    'consents.retired_purpose':
      'Zu diesem Punkt wird heute keine Zustimmung mehr eingeholt. Was Sie damals zugestimmt haben, steht '
      + 'weiterhin hier.',

    // ---- Hinweise auf dem Einstellungsbildschirm ----
    //
    // Nicht als Fussnote. Jedes Mitglied erhält diese Angaben, unabhängig von einer erfassten Zeile, und
    // die überraschendere der beiden Tatsachen steht darin: ein festgehaltener Entscheid lässt sich nicht
    // löschen, auch nicht von eigentliCH, und übersteht eine Löschung geleert.
    'notices.heading': 'Wovon eigentliCH Sie in Kenntnis setzt',
    'notices.lede':
      'Das Folgende gehört zum Dienst. Es wird Ihnen mitgeteilt und nicht zur Wahl gestellt — hier ist '
      + 'nichts anzukreuzen und nichts zu widerrufen.',
    'notices.kind': 'Hinweis',
    'notices.consequence': 'Warum das nicht zur Wahl steht',

    // ---- Einstellungen: die Seite selbst ----
    'settings.eyebrow': 'Einstellungen',
    'settings.title': 'Einstellungen',
    'settings.lede': 'Ihre Zustimmungen, Ihre Daten und der Weg hinaus.',
    'settings.nav': 'Einstellungen',
    'settings.export_heading': 'Alle Ihre Daten holen',
    'settings.export_hint':
      'Sie erhalten eine Datei mit allem, was eigentliCH über Sie festgehalten hat — einschliesslich der '
      + 'hinterlegten Unterlagen samt Inhalt. Dass Sie sie angefordert haben, wird als Entscheid '
      + 'protokolliert.',
    'settings.export': 'Datei anfordern',
    'settings.export_ready': 'Die Datei liegt bereit.',
    'settings.export_decision': 'Als Entscheid festgehalten',
    'settings.export_working': 'Die Datei wird zusammengestellt.',

    // ---- R-231: die Löschung ----
    //
    // Zwei Schritte, und der erste ist eine Tür, die man aufmachen muss. Der Weg dorthin ist absichtlich
    // nicht bequem: es gibt keinen Weg zurück.
    'erasure.heading': 'Konto und Daten löschen',
    'erasure.hint':
      'Dies löscht Ihr Konto und Ihre Angaben. Es gibt danach keinen Weg zurück und keine Kopie bei '
      + 'eigentliCH, aus der sich etwas wiederherstellen liesse.',
    'erasure.open': 'Löschung vorbereiten',
    'erasure.close': 'Nicht löschen',
    'erasure.title': 'Konto und Daten löschen',
    'erasure.irreversible': 'Dieser Schritt ist endgültig.',
    'erasure.what_goes':
      'Gelöscht werden: Ihr Konto, Ihre Zugangsdaten, Ihre Positionen, Ihre Ziele, Ihre Antworten, Ihre '
      + 'Dokumente samt Dateien und Ihre Sitzungen.',
    'erasure.what_stays_heading': 'Was bestehen bleibt',
    'erasure.what_stays':
      'Die protokollierten Entscheidungen und das Protokoll einer Beratung bleiben als Zeilen bestehen. Sie '
      + 'werden geleert: Ihr Name und Ihre Texte werden entfernt, die Verbindung zu Ihnen wird gelöst. '
      + 'Diese Zeilen lassen sich auf der Datenbankebene nicht entfernen, nicht von Ihnen und nicht von '
      + 'eigentliCH.',
    'erasure.phrase_label': 'Tippen Sie zur Bestätigung genau diesen Satz',
    'erasure.phrase_hint': 'Wort für Wort, mit Grossbuchstaben. Kopieren geht auch.',
    'erasure.password_label': 'Ihr Passwort',
    'erasure.password_hint':
      'Zusätzlich zum Satz. Eine offene Sitzung auf einem geliehenen Rechner soll nicht genügen, um einen '
      + 'Datensatz zu zerstören.',
    'erasure.reason_label': 'Grund (optional)',
    'erasure.reason_hint':
      'Wird auf dem Entscheid festgehalten, der die Löschung protokolliert — und von der Löschung selbst '
      + 'wieder entfernt.',
    'erasure.submit': 'Jetzt endgültig löschen',
    'erasure.phrase_missing': 'Bitte tippen Sie den Satz genau so, wie er oben steht.',
    'erasure.password_missing': 'Bitte geben Sie Ihr Passwort ein.',
    'erasure.done_heading': 'Gelöscht',
    'erasure.done_lede':
      'Ihr Konto ist gelöscht und diese Sitzung ist beendet. Was hier steht, ist die Quittung — sie '
      + 'verschwindet, sobald Sie diese Seite verlassen.',
    'erasure.done_deleted': 'Entfernt',
    'erasure.done_redacted': 'Geleert',
    'erasure.done_decision': 'Entscheid, der die Löschung festhält',
    'erasure.done_announced': 'Das Konto ist gelöscht. Die Sitzung ist beendet.',
    'erasure.rows': 'Zeilen',

    // ---- S-10: die Fähigkeiten (D-01 / R-194) ----
    //
    // D-01 ist beantwortet: eine Fähigkeit ist die Selbsteinschätzung des Mitglieds. eigentliCH prüft
    // nicht, benotet nicht und bescheinigt nichts. Deshalb steht hier kein Wort, das eine Beurteilung
    // andeutet — keine Stufe, keine Prüfung, kein Nachweis im Sinne eines Zeugnisses.
    'capabilities.eyebrow': 'Wissen & Gemeinschaft',
    'capabilities.title': 'Was Sie können',
    'capabilities.lede':
      'Diese Sätze beschreiben, was jemand nach der Arbeit mit den Lerneinheiten von den eigenen Zahlen '
      + 'behaupten kann. Sie halten selbst fest, welche davon für Sie zutreffen.',
    'capabilities.self_assessed':
      'Das ist Ihre eigene Einschätzung. eigentliCH prüft sie nicht, benotet sie nicht und bescheinigt '
      + 'nichts. Es gibt keine Reihenfolge und keine Stufen — jeder Satz steht für sich.',
    'capabilities.no_qualification':
      'eigentliCH beansprucht keine amtliche oder anerkannte Stellung und stellt keine Bescheinigung aus.',
    'capabilities.fictional':
      'Die Sätze und die Lerneinheiten sind für diesen Aufbau erfunden und noch nicht redaktionell '
      + 'geprüft.',
    'capabilities.asserted': 'Von Ihnen festgehalten.',
    'capabilities.asserted_on': 'Festgehalten am',
    'capabilities.assert': 'Trifft auf mich zu',
    'capabilities.assert_heading': 'Selbst festhalten',
    'capabilities.assert_hint':
      'Sie halten fest, dass dieser Satz für Sie zutrifft. Das ist Ihre Aussage über sich selbst.',
    'capabilities.evidence_unit_label': 'Dazu gearbeitete Lerneinheit (optional)',
    'capabilities.evidence_unit_hint':
      'Nur Einheiten, deren Inhalt genau diesen Satz belegt, stehen hier zur Wahl. Ohne Angabe steht Ihre '
      + 'Aussage für sich.',
    'capabilities.evidence_unit_none': 'Keine angeben',
    'capabilities.evidence_unit': 'Lerneinheit',
    'capabilities.evidence_self': 'Eigene Aussage, ohne Verweis auf eine Lerneinheit.',
    'capabilities.assert_save': 'Festhalten',
    'capabilities.assert_cancel': 'Abbrechen',
    'capabilities.asserted_announced': 'Festgehalten.',
    'capabilities.already': 'Das ist bereits festgehalten.',
    'capabilities.no_removal':
      'Ein festgehaltener Satz lässt sich hier nicht zurücknehmen. Was ein Rückzug für ein Angebot '
      + 'bedeuten würde, das darauf beruht, ist nicht entschieden — und diese Frage in einem Formular zu '
      + 'beantworten wäre der falsche Ort.',
    'capabilities.units_heading': 'Die Lerneinheiten dazu',
    'capabilities.announced': 'Die Fähigkeiten sind geladen.',
    'capabilities.know_panel_note':
      'Das Wissenspanel am rechten Rand ist etwas anderes und begleitet Sie auf jedem Bildschirm.',

    // ---- R-122 / R-123: eine Position ändern ----
    'position.edit': 'Position ändern',
    'position.edit_title': 'Position ändern',
    'position.edit_hint':
      'Die Position wird geändert und der frühere Stand als Entscheid festgehalten. Beide Stände stehen '
      + 'in diesem Eintrag.',
    'position.edit_save': 'Änderung festhalten',
    'position.edit_unchanged':
      'Es ist nichts geändert. Ein Entscheid, der eine Änderung behauptet, die es nicht gab, bleibt '
      + 'dauerhaft stehen — deshalb wird er nicht geschrieben.',
    'position.edit_liquidity': 'Verfügbarkeit',
    'position.edit_liquidity_hint':
      'Eines der vier Bänder, nie eine Anzahl Jahre: eine Schwelle in Jahren wäre eine Annahme, und '
      + 'niemand hat eine veröffentlicht. Was hier steht, ist die bisherige Angabe.',
    // A99 lieferte «liquidity» in die Übersicht, deshalb heisst die erste Möglichkeit jetzt «nicht
    // angegeben» und nicht mehr «unverändert lassen»: die bisherige Angabe steht vorgewählt da, und
    // «nicht angegeben» ist eine Angabe, die sich wieder wählen lässt.
    'position.liquidity_choose': 'Nicht angegeben',
    'position.liquidity_immediate': 'Sofort verfügbar',
    'position.liquidity_within_months': 'Innerhalb von Monaten verfügbar',
    'position.liquidity_within_years': 'Innerhalb von Jahren verfügbar',
    'position.liquidity_illiquid': 'Nicht frei verfügbar',
    // R-122 hat seine eigene Schaltfläche, und das ist keine Vorsicht: ein Häkchen mitten in einem
    // Änderungsformular ist der Weg, auf dem eine Position versehentlich stillgelegt wird.
    'position.deactivate': 'Aus dem laufenden Plan nehmen',
    'position.deactivate_heading': 'Aus dem laufenden Plan nehmen',
    'position.deactivate_hint':
      'Diese Position zählt danach im Befund nicht mehr mit, die Illustration rechnet nicht mehr mit ihr, '
      + 'und die Ableitungen lassen sie aus.',
    'position.deactivate_stays':
      'Gelöscht wird nichts. Die Position bleibt in der Übersicht als nicht mehr aktiv stehen und bleibt '
      + 'mit jedem Entscheid verbunden, der sie erwähnt.',
    'position.deactivate_save': 'Stilllegen',
    'position.reactivate': 'Wieder in den laufenden Plan',
    'position.reactivate_heading': 'Wieder in den laufenden Plan',
    'position.reactivate_hint':
      'Diese Position zählt danach im Befund wieder mit, und die Illustration rechnet wieder mit ihr.',
    'position.reactivate_save': 'Wieder aufnehmen',
    'position.status_cancel': 'Abbrechen',
    'position.deactivated_announced': 'Die Position ist stillgelegt. Sie steht weiterhin in der Übersicht.',
    'position.reactivated_announced': 'Die Position ist wieder im laufenden Plan.',
    'position.changed_announced': 'Die Änderung ist festgehalten.',
    'position.decision_heading': 'Was halten wir fest?',
    'position.decision_hint':
      'Auch diese Änderung wird mit ihrer Begründung festgehalten. Das bleibt Ihr Protokoll.',
    'position.see_decisions': 'Entscheidungen zu dieser Position',

    'error.load': 'Die Positionen konnten nicht geladen werden.',
    'error.detail': 'Grund',

    // ================================================================================================
    // R-210 / R-213 — der Zugang für Kuratoren, erteilt und entzogen
    // ================================================================================================
    //
    // Die drei Sätze `scoped`, `time_limited` und `immediate` sind die Anforderung selbst, in der
    // Sprache des Mitglieds. Sie stehen auf dem Bildschirm, bevor irgendein Bedienelement kommt: wer
    // etwas freigibt, muss vorher lesen können, was eine Freigabe ist.
    'grants.nav': 'Zugang für Kuratoren',
    'grants.eyebrow': 'Ihre Entscheidung',
    'grants.title': 'Zugang für Kuratoren',
    'grants.lede':
      'Hier steht, wer etwas von Ihnen sehen darf, welche Bereiche das sind und bis wann. Ohne einen '
      + 'offenen Zugang sieht eine Kuratorin oder ein Kurator nichts von Ihnen — auch dann nicht, wenn '
      + 'ein Gespräch bereits eröffnet ist.',
    'grants.scoped': 'Ein Zugang nennt einzelne Bereiche. Es gibt keine Freigabe für alles.',
    'grants.time_limited': 'Ein Zugang endet zu einem festen Zeitpunkt. Einen Zugang ohne Ende gibt es nicht.',
    'grants.immediate':
      'Ein Zugang, den Sie entziehen, ist von diesem Moment an geschlossen. Die nächste Abfrage dieser '
      + 'Person wird abgewiesen.',
    'grants.no_pending':
      'Es gibt keinen Zwischenzustand: keine Wartezeit, keine Freigabe durch Dritte und keine '
      + 'Bestätigung im Nachhinein.',
    'grants.no_blanket_access':
      'Der Server kennt weder eine Sammelfreigabe noch eine Freigabe bis auf Widerruf.',
    'grants.scopes_label': 'Freigegebene Bereiche',
    'grants.scope_positions': 'Positionen',
    'grants.scope_positions_covers': 'Was Sie erfasst haben, über beide Arten von Kapital.',
    'grants.scope_goals': 'Ziele',
    'grants.scope_goals_covers': 'Worauf Sie hinarbeiten, samt Betrag und Zeitraum, wo Sie einen genannt haben.',
    'grants.scope_decisions': 'Entscheidungen',
    'grants.scope_decisions_covers':
      'Ihr Protokoll: welche Frage sich stellte, wie Sie entschieden haben und weshalb.',
    'grants.scope_vault': 'Unterlagen',
    'grants.scope_vault_covers':
      'Ihre hinterlegten Dokumente. Das ist die empfindlichste der vier Klassen im ganzen Bestand.',
    'grants.scope_action_items': 'Vorbereitete Entscheidungen',
    'grants.scope_action_items_covers': 'Was im Wissensfenster für Sie vorbereitet liegt.',
    'grants.granted_at': 'Erteilt am',
    'grants.expires_at': 'Endet am',
    'grants.revoked_at': 'Entzogen am',
    'grants.open_heading': 'Offene Zugänge',
    'grants.none_open':
      'Derzeit ist kein Zugang offen. Sobald Sie einen erteilen, steht er hier mit den freigegebenen '
      + 'Bereichen und dem Enddatum.',
    'grants.ended_heading': 'Beendete Zugänge',
    'grants.ended_hint':
      'Diese Zugänge sind geschlossen. Sie bleiben sichtbar, weil festgehalten bleibt, dass es sie gab.',
    'grants.ended_withdrawn': 'Diesen Zugang haben Sie entzogen.',
    'grants.ended_lapsed': 'Dieser Zugang ist abgelaufen.',
    'grants.record_kept':
      'Der Zugang ist geschlossen. Der Eintrag darüber, dass er bestand, bleibt erhalten und wird nicht '
      + 'gelöscht.',
    'grants.revoke': 'Zugang entziehen',
    'grants.revoke_hint': 'Wirkt sofort. Die nächste Abfrage dieser Person wird abgewiesen.',
    'grants.revoked_announced': 'Der Zugang ist entzogen.',
    'grants.curator_unnamed': 'Nicht im Verzeichnis',
    'grants.curator_not_in_directory':
      'Diese Person steht nicht im Verzeichnis der ansprechbaren Kuratorinnen und Kuratoren. Angezeigt '
      + 'wird die Kennung, die im Zugang steht; ein Name wird hier nicht erfunden.',
    'grants.new_open': 'Zugang erteilen',
    'grants.new_heading': 'Neuen Zugang erteilen',
    'grants.new_hint': 'Drei Angaben: wer, welche Bereiche, bis wann. Nichts davon ist vorausgewählt.',
    'grants.choose_curator': 'Wer soll etwas sehen dürfen?',
    'grants.choose_curator_none': 'Bitte auswählen',
    'grants.choose_curator_hint': 'Das Verzeichnis nennt die Kuratorinnen und Kuratoren, die ansprechbar sind.',
    'grants.no_curators':
      'Das Verzeichnis nennt derzeit niemanden. Ohne eine benannte Person entsteht kein Zugang.',
    'grants.choose_scopes': 'Welche Bereiche?',
    'grants.choose_scopes_hint':
      'Diese Liste kommt vom Server. Ein Bereich, der hier nicht angekreuzt ist, bleibt verschlossen.',
    'grants.choose_window': 'Bis wann?',
    'grants.choose_window_none': 'Bitte auswählen',
    'grants.choose_window_hint': 'Jeder Zugang endet. Ein Zugang ohne Ende ist nicht vorgesehen.',
    'grants.window_one_hour': 'Eine Stunde',
    'grants.window_hours': '{n} Stunden',
    'grants.window_one_day': 'Ein Tag',
    'grants.window_days': '{n} Tage',
    'grants.window_usual': 'üblicher Zeitraum',
    'grants.submit': 'Zugang erteilen',
    'grants.granted_announced': 'Der Zugang ist erteilt.',
    'grants.no_curator_chosen': 'Es ist noch keine Person ausgewählt.',
    'grants.no_scope_chosen': 'Es ist noch kein Bereich angekreuzt. Ein Zugang ohne Bereich gibt nichts frei.',
    'grants.no_window_chosen': 'Es ist noch kein Zeitraum ausgewählt.',
    'grants.announced': 'Zugang für Kuratoren geladen.',
    // Der Satz, der im Wissensfenster in dem Moment erscheint, in dem ein Gespräch eröffnet wurde.
    'know.curator_sees_nothing':
      'Das Gespräch ist festgehalten. Freigegeben ist damit nichts: Ohne einen Zugang sieht diese Person '
      + 'keine Ihrer Angaben.',
    'settings.grants_heading': 'Zugang für Kuratoren',
    'settings.grants_lede':
      'Wer etwas von Ihnen sehen darf, welche Bereiche das sind und bis wann. Ein Entzug wirkt sofort.',

    // ================================================================================================
    // S-11 — der Marktplatz
    // ================================================================================================
    'market.eyebrow': 'Marktplatz',
    'market.title': 'Marktplatz',
    'market.lede':
      'Angebote sind nach den vier Rollen geordnet, nicht nach Beruf. Anbieter und Angebote von '
      + 'Mitgliedern stehen in einer Liste nebeneinander.',
    'market.not_gated':
      'Lesen und Kontakt aufnehmen sind an keine Bedingung geknüpft. Es gibt hier nichts freizuschalten.',
    'market.fictional_all': 'Die Anbieter und Angebote in dieser Liste sind erfunden.',
    'market.filter_heading': 'Filter',
    'market.filter_from_grid': 'Die Liste ist auf die Rollen eingeschränkt, die in Ihrem Plan vorkommen.',
    'market.filter_chosen': 'Die Liste ist auf die von Ihnen gewählten Rollen eingeschränkt.',
    'market.filter_removed': 'Der Filter ist aufgehoben. Die Liste zeigt alle Rollen.',
    'market.filter_grid_empty': 'Ihr Plan nennt noch keine Rolle, deshalb ist nichts eingeschränkt.',
    'market.filter_none': 'Es ist kein Filter gesetzt.',
    'market.filter_remove': 'Filter aufheben',
    'market.ordering_heading': 'Reihenfolge',
    'market.ordering_not_for_sale':
      'Die Reihenfolge dieser Liste ist nicht käuflich. Sie entsteht aus drei Angaben und aus keiner '
      + 'weiteren.',
    'market.ordering_input_role_match': 'Übereinstimmung mit den gesuchten Rollen',
    'market.ordering_input_capability_evidence': 'Belegte Fähigkeiten',
    'market.ordering_input_community_presence': 'Anwesenheit in der Gemeinschaft',
    'market.ordering_share':
      'Die Übereinstimmung zählt als Anteil dessen, was ein Eintrag selbst angibt. Wer viele Rollen '
      + 'angibt, gewinnt dadurch nichts.',
    'market.no_qualification':
      'eigentliCH erteilt keine Qualifikation und prüft keine. Angaben zu Registrierungen gehören dem '
      + 'Anbieter, der sie geliefert hat.',
    'market.kind_provider_listing': 'Anbieter',
    'market.kind_member_offer': 'Angebot eines Mitglieds',
    'market.roles_label': 'Rollen',
    'market.domain_label': 'Bereich',
    'market.domain_financial': 'Finanzen',
    'market.domain_health': 'Gesundheit',
    'market.domain_education': 'Bildung',
    'market.pipeline_label': 'Nachweisweg',
    'market.pipeline_capability': 'Belegte Fähigkeiten',
    'market.pipeline_professional_registration': 'Berufliche Registrierung',
    'market.registration_refs_label': 'Angaben zur Registrierung',
    'market.registration_refs_own':
      'Diese Angaben stammen vom Anbieter selbst. eigentliCH hat sie nicht geprüft.',
    'market.supplier_label': 'Anbieter',
    'market.contact_heading': 'Kontakt',
    'market.contact_not_gated': 'Der Kontakt ist an keine Bedingung geknüpft.',
    'market.contact_offer': 'Kontaktweg anzeigen',
    'market.contact_via_member':
      'Ein Angebot eines Mitglieds wird über das Mitglied erreicht. Deshalb steht dort keine Adresse, '
      + 'sondern eine Kennung.',
    'market.disclosures_heading': 'Offenlegungen',
    'market.disclosures_absent':
      'Dieser Eintrag nennt keine Offenlegung. Das sollte nicht vorkommen: Ein Eintrag erreicht den '
      + 'Marktplatz nur über die Offenlegung.',
    'market.disclosure_declared_by': 'Erklärt von',
    'market.disclosure_none_declared': 'Nichts zu erklären',
    'market.disclosure_commission_from_third_party': 'Vergütung von Dritten',
    'market.disclosure_own_working_document': 'Eigenes Arbeitsmittel',
    'market.disclosure_referral_arrangement': 'Vermittlungsabsprache',
    'market.disclosure_shared_ownership': 'Gemeinsame Eigentümerschaft',
    'market.offer_kind_co_investment': 'Gemeinsame Anlage',
    'market.offer_kind_succession': 'Nachfolge',
    'market.offer_kind_property': 'Liegenschaft',
    'market.offer_kind_skills': 'Fähigkeiten',
    'market.offer_kind_services': 'Dienstleistungen',
    'market.direction_offer': 'wird angeboten',
    'market.direction_search': 'wird gesucht',
    'market.fictional': 'Erfundener Eintrag.',
    'market.open_listing': 'Eintrag öffnen',
    'market.back': 'Zurück zur Liste',
    'market.no_entries':
      'Zu diesen Rollen steht derzeit kein Eintrag im Marktplatz. Hier stünden Anbieter und Angebote '
      + 'von Mitgliedern nebeneinander.',
    'market.status_label': 'Stand',
    'market.status_draft': 'Entwurf',
    'market.status_published': 'Im Marktplatz',
    'market.announced': 'Marktplatz geladen.',
    'market.announced_one': 'Eintrag geladen.',
    'market.apply_open': 'Selbst als Angebot erscheinen',
    'market.apply_heading': 'Selbst als Angebot erscheinen',
    'market.apply_lede':
      'Ein Eintrag im Marktplatz ist eine Erklärung über Sie selbst: was Sie anbieten, unter welchen '
      + 'Rollen es erscheint und über welchen Weg der Eintrag belegt ist.',
    'market.apply_only_gate':
      'Dies ist der einzige Vorgang auf dieser Seite mit einer Bedingung. Lesen und Kontakt aufnehmen '
      + 'haben keine.',
    'market.apply_display_name': 'Unter welchem Namen soll der Eintrag erscheinen?',
    'market.apply_title': 'Titel des Eintrags',
    'market.apply_summary': 'Kurzbeschreibung (optional)',
    'market.apply_contact': 'Kontaktangabe (optional)',
    'market.apply_domain': 'Bereich',
    'market.apply_domain_choose': 'Bitte auswählen',
    'market.apply_domain_hint':
      'Angeboten sind die Bereiche, die der Marktplatz heute führt. Der Bereich bestimmt den Nachweisweg.',
    'market.apply_gate_capability': 'belegt über eine Fähigkeit, die Sie selbst festgehalten haben',
    'market.apply_gate_registration': 'belegt über eine berufliche Registrierung',
    'market.apply_roles': 'Rollen, unter denen der Eintrag erscheint',
    'market.apply_roles_hint':
      'Ein Eintrag kann unter mehreren Rollen stehen. Mehr Rollen anzugeben verbessert die Reihenfolge '
      + 'nicht.',
    'market.apply_refs': 'Angaben zur Registrierung',
    'market.apply_refs_hint':
      'Mehrere Angaben mit Komma trennen. Sie stammen von Ihnen; eigentliCH prüft sie nicht.',
    'market.apply_submit': 'Eintrag anmelden',
    'market.apply_no_domain': 'Es ist noch kein Bereich ausgewählt.',
    'market.apply_no_role': 'Es ist noch keine Rolle angekreuzt.',
    'market.applied_announced': 'Der Entwurf ist angelegt.',
    'market.draft_heading': 'Entwurf',
    'market.draft_not_listed': 'Dieser Entwurf steht noch nicht im Marktplatz.',
    'market.draft_only_here':
      'Der Entwurf ist von dieser Ansicht aus erreichbar und sonst von nirgends: Es gibt keine Liste '
      + 'eigener Entwürfe, und nach einem Neuladen der Seite ist die Kennung nicht mehr auffindbar.',
    'market.draft_needs_disclosure':
      'Bevor der Eintrag erscheinen kann, braucht er mindestens eine Offenlegung.',
    'market.disclosure_kind': 'Art der Offenlegung',
    'market.disclosure_kind_choose': 'Bitte auswählen',
    'market.disclosure_kind_hint':
      'Auch die Erklärung, dass es nichts zu erklären gibt, ist eine Offenlegung. Ein leeres Feld ist keine.',
    'market.disclosure_statement': 'Wortlaut der Offenlegung',
    'market.disclosure_add': 'Offenlegung festhalten',
    'market.disclosure_recorded': 'Die Offenlegung ist festgehalten.',
    'market.disclosure_missing_fields': 'Art und Wortlaut werden beide gebraucht.',
    'market.publish': 'Eintrag veröffentlichen',
    'market.published_announced': 'Der Eintrag ist veröffentlicht.',

    // ================================================================================================
    // S-05 — die Lebensabschnitte
    // ================================================================================================
    'stages.nav': 'Lebensabschnitte',
    'stages.eyebrow': 'Plan',
    'stages.title': 'Lebensabschnitte',
    'stages.lede':
      'Fünf Situationen, die im Leben vorkommen, und die Fragen, die sie aufwerfen. Keine Einteilung und '
      + 'keine Folge, die Sie durchlaufen müssten.',
    // D-07. The lead-in only; the phrase itself comes from the content record over the wire, so
    // this table never holds a second copy of it.
    'stages.destination_lead': 'Wohin das alles führt: ',
    'stages.all_open': 'Jede dieser Situationen können Sie öffnen, unabhängig von Ihrem Alter.',
    'stages.not_a_position':
      'Die Übersicht öffnet an einer Stelle. Das ist keine Aussage darüber, wo Sie stehen.',
    'stages.age_marker': 'Alter, in dem diese Situation üblicherweise auftritt',
    'stages.age_marker_not_a_condition':
      'Diese Zahl ist keine Bedingung für den Zugang und wird mit Ihrem Alter nicht verglichen.',
    'stages.questions': 'Fragen, die diese Situation aufwirft',
    'stages.opens_here': 'Hier öffnet die Übersicht.',
    'stages.draft_wording': 'Wortlaut noch nicht gelesen',
    'stages.no_stage_after': 'Nach {age} folgt keine weitere Situation.',
    'stages.no_stage_after_reason':
      'Das Leben aus dem Vermögen, Kapital gegen Rente und der Zeitpunkt des AHV-Bezugs sind bewusst '
      + 'ausgeklammert. Das ist eine Entscheidung und kein Versäumnis.',
    'stages.announced': 'Lebensabschnitte geladen.',

    // ================================================================================================
    // S-09 — die Lebensereignisse. R-222: dies ist die Stelle, an der das Wort Ereignis gilt.
    // ================================================================================================
    'life_events.nav': 'Lebensereignisse',
    'life_events.eyebrow': 'Plan',
    'life_events.title': 'Lebensereignisse',
    'life_events.lede':
      'Sieben Situationen, in denen es schnell gehen muss. Der Rahmen steht; die Inhalte sind noch nicht '
      + 'geschrieben.',
    'life_events.none_written': 'Keines der sieben Module ist inhaltlich geschrieben.',
    'life_events.not_written': 'Der Inhalt dieses Moduls ist noch nicht geschrieben.',
    'life_events.not_written_why':
      'Diese Inhalte werden von Menschen geschrieben und nicht erzeugt. Deshalb steht hier der Rahmen '
      + 'und kein Text, für den niemand einstehen könnte.',
    'life_events.frame_heading': 'Was jedes Modul enthalten wird',
    'life_events.first_steps': 'Erste Schritte',
    'life_events.do_not_sign': 'Was jetzt nicht unterschrieben wird',
    'life_events.vault_kinds': 'Welche Unterlagen hier zählen',
    'life_events.curator_role': 'Was eine Kuratorin hier tut',
    'life_events.field_unwritten': 'Noch nicht geschrieben.',
    'life_events.vault_kinds_unwritten': 'Noch nicht festgelegt.',
    'life_events.retrieval_unavailable':
      'Es wurde nach keiner Unterlage gesucht, weil dieses Modul noch nicht festlegt, welche Arten hier '
      + 'zählen. Das ist etwas anderes als eine leere Ablage.',
    'life_events.your_documents': 'Ihre Unterlagen dazu',
    'life_events.no_documents': 'Zu diesen Arten haben Sie keine Unterlage hinterlegt.',
    'life_events.expires': 'Läuft ab am',
    'life_events.authored_by': 'Geschrieben von',
    'life_events.open': 'Modul öffnen',
    'life_events.back': 'Zurück zur Übersicht',
    'life_events.announced': 'Lebensereignisse geladen.',
    'life_events.announced_one': 'Modul geladen.',
    // Die sieben Namen. Das ist keine Inhaltsarbeit und kein Verstoss gegen R-183: die Liste der sieben
    // Situationen steht in der Spezifikation selbst, und der Server liefert `title` als null, weil er die
    // geschriebenen Inhalte meint. Ein Bildschirm mit sieben leeren Karten wäre kein Rahmen.
    'life_events.module_separation': 'Trennung',
    'life_events.module_job_loss': 'Verlust der Arbeitsstelle',
    'life_events.module_illness_and_incapacity': 'Krankheit und Erwerbsunfähigkeit',
    'life_events.module_death_of_a_partner': 'Tod der Partnerin oder des Partners',
    'life_events.module_inheritance': 'Erbschaft',
    'life_events.module_caring_for_parents': 'Betreuung der Eltern',
    'life_events.module_move_abroad_or_return': 'Wegzug ins Ausland oder Rückkehr',

    // ================================================================================================
    // S-13 — Vorträge und Treffen. R-222: keines dieser Wörter ist Ereignis, Anlass oder Veranstaltung.
    // ================================================================================================
    'community.nav': 'Gemeinschaft',
    'community.eyebrow': 'Gemeinschaft',
    'community.title': 'Vorträge und Treffen',
    'community.lede': 'Was angesetzt ist, und wo Sie dabei waren.',
    'community.not_a_standing':
      'Ihre Anwesenheit wird festgehalten und nicht gezählt. Sie ist eine von drei Angaben, aus denen '
      + 'die Reihenfolge im Marktplatz entsteht, und keine Bewertung Ihrer Person.',
    'community.kind_lecture': 'Vortrag',
    'community.kind_cafe_evening': 'Café-Abend',
    'community.kind_meetup': 'Treffen',
    'community.held_on': 'Datum',
    'community.location': 'Ort',
    'community.you_were_there': 'Sie waren dabei.',
    'community.was_there': 'Ich war dabei',
    'community.recorded_announced': 'Ihre Anwesenheit ist festgehalten.',
    'community.none_scheduled':
      'Derzeit ist nichts angesetzt. Hier stünden Vorträge, Café-Abende und Treffen mit Datum und Ort.',
    'community.who_schedules':
      'Diese Termine setzt eigentliCH an. Für Mitglieder gibt es hier bewusst kein Formular dafür.',
    'community.fictional': 'Erfundener Termin.',
    'community.announced': 'Vorträge und Treffen geladen.',

    // ================================================================================================
    // S-10 — der Lernweg
    // ================================================================================================
    'capabilities.nav': 'Fähigkeiten',
    'learning.nav': 'Lernweg',
    'learning.eyebrow': 'Wissen',
    'learning.title': 'Lernweg',
    'learning.lede': 'Was es zu lernen gibt, was jede Einheit belegt, und wohin das führt.',
    'learning.no_scheme': 'Es gibt keine Einteilung in Stufen. Nicht eine offene, sondern keine.',
    'learning.not_gated': 'Keine Einheit ist gesperrt.',
    'learning.unordered': 'Die Folge dieser Liste ist keine Folge zum Durcharbeiten.',
    'learning.self_asserted': 'Was Sie können, halten Sie selbst fest. eigentliCH prüft es nicht.',
    'learning.no_qualification': 'eigentliCH erteilt keine Qualifikation.',
    'learning.follows': 'Steht im Zusammenhang mit',
    'learning.follows_open': 'Dazu haben Sie noch nichts festgehalten.',
    'learning.evidences': 'Diese Einheit belegt',
    'learning.you_asserted': 'Sie haben festgehalten, dass das für Sie zutrifft.',
    'learning.not_asserted': 'Dazu ist noch nichts festgehalten.',
    'learning.leads_to': 'Führt zu',
    'learning.body_not_written': 'Der Lehrtext dieser Einheit ist noch nicht geschrieben.',
    'learning.fictional': 'Erfundene Einheit.',
    'learning.exits_heading': 'Wohin das führt',
    'learning.exits_lede': 'Drei Wege. Nur zwei davon haben mit dem Marktplatz zu tun.',
    'learning.exit_touches_market': 'Führt in den Marktplatz.',
    'learning.exit_no_market': 'Hat mit dem Marktplatz nichts zu tun.',
    'learning.announced': 'Lernweg geladen.',

    // ================================================================================================
    // R-232 — welche Klasse jede gespeicherte Kategorie hat
    // ================================================================================================
    'settings.classes_heading': 'Wie Ihre Angaben eingeteilt sind',
    'settings.classes_lede':
      'Jede gespeicherte Kategorie fällt in eine von vier Klassen. Diese Aufstellung entsteht aus dem '
      + 'Datenmodell selbst und wird nicht von Hand geführt.',
    'settings.classes_scheme': 'Die vier Klassen',
    'settings.class_k0': 'Veröffentlicht und unpersönlich: Rollendefinitionen, Annahmen, Lerninhalte.',
    'settings.class_k1': 'Identifizierend, wenig empfindlich: Anzeigename, Sprache, Einwilligungen.',
    'settings.class_k2': 'Persönlich und inhaltlich: Positionen, Ziele, Entscheidungen.',
    'settings.class_k3':
      'Persönlich und dokumentarisch: hinterlegte Unterlagen und was daraus gelesen wurde.',
    'settings.classes_top_stays':
      'Was in {class} fällt, wird nicht protokolliert und nicht an Dritte weitergegeben. Hinaus geht es '
      + 'nur, wo Sie es selbst veranlassen: in Ihre eigene Kopie unter «Alle Ihre Daten holen», die die '
      + 'hinterlegten Unterlagen samt Inhalt enthält, und in das Verzeichnis Ihrer Ablage, das eine '
      + 'Kuratorin oder ein Kurator sieht, solange Sie Einsicht gegeben haben — die Dateien selbst nie.',
    'settings.classes_categories': 'Die gespeicherten Kategorien',
    'settings.classes_yours': 'Enthält Angaben zu Ihnen.',
    'settings.classes_not_yours': 'Enthält keine Angaben zu einer Person.',
    'settings.classes_can_leave': 'Darf den Server verlassen.',
    'settings.classes_stays': 'Bleibt auf dem Server, ausser in Ihrer eigenen Kopie.',
    'settings.classes_field_above': 'Einzelne Felder liegen höher',
    'settings.classes_link_tables':
      'Verbindungstabellen führen keine eigene Klasse; sie tragen die Klasse der Einträge, die sie '
      + 'verbinden. Sie stehen deshalb nicht in dieser Liste.',
    'settings.classes_derived':
      'Diese Aufstellung entsteht bei jeder Abfrage neu aus dem Datenmodell und kann deshalb nicht '
      + 'veralten.',
  },
  en: {
    'grid.eyebrow': 'Plan',
    'grid.title': 'Your positions',
    'grid.lede':
      'Four roles across two kinds of capital. What you can do and what you own sit side by side, '
      + 'because each can stand in for the other.',
    'grid.provisional': 'definitions provisional',
    'grid.one_position': 'One position recorded.',
    'grid.n_positions': 'Positions recorded: {n}.',
    'capital.human': 'Human capital',
    'capital.financial': 'Financial capital',
    'cell.add': 'Record a position',
    'cell.what_is_this': 'What belongs here?',
    'position.inactive': 'no longer active',
    'unit.chf_per_year': 'CHF per year',
    'unit.share_of_total': 'share of total',
    'form.title': 'Record a position',
    'form.label': 'What do you call this position?',
    'form.label_hint': 'A short name you will recognise in a year.',
    'form.description': 'Description (optional)',
    'form.magnitude': 'Amount (optional)',
    'form.magnitude_hint': 'Leave empty when no franc figure fits. A position without an amount is a full position.',
    'form.unit': 'What does the amount refer to?',
    'form.unit_hint': 'Never guessed, which is why the question is here. An annual amount and a share of the total are not the same thing. Convert a monthly figure to a year.',
    'form.unit_choose': 'Please choose',
    'form.unit_missing': 'Please state what the amount refers to. An amount without it would be a number nobody can read.',
    'form.time_basis': 'Time basis',
    'form.time_basis_hint': 'For example 42 hours a week. For human capital, time is the binding constraint.',
    'form.tags': 'Classification (optional)',
    'form.tags_hint': 'In your own words. These are stored and are not interpreted today.',
    'form.decision': 'What are we recording?',
    'form.decision_hint': 'Every change to the plan is recorded with its reason. This stays your record.',
    'form.question': 'Question',
    'form.choice': 'Decision',
    'form.default_question': '{role}: record a position?',
    'form.save': 'Record',
    'form.cancel': 'Cancel',
    'tag.client_type': 'Kind of client',
    'tag.skill': 'Skill',
    'tag.reputation_basis': 'What the reputation rests on',
    'tag.sector': 'Sector',
    'tag.time_basis': 'Time basis',
    // ---- A11: the chrome, and the three states of getting in. See the German block for the note. ----
    'chrome.skip': 'Skip to content',
    'chrome.nav_label': 'Main navigation',
    'chrome.door_vault': 'Vault',
    'chrome.home': 'To the question',
    'chrome.door_plan': 'Plan & life events',
    // See the German block on why the fourth door exists.
    'chrome.door_befund': 'Report',
    'chrome.door_know': 'Know',
    'chrome.door_market': 'Market',
    // ---- A12 / A26: the language switch. See the German block for why the options are not translated. ----
    'chrome.language': 'Language',
    'language.changed': 'The language has changed.',
    'language.not_saved': 'The language could not be saved. The previous one still applies.',
    'language.this_device_only': 'Before you sign in the choice applies to this window only — there is no account yet for it to sit on.',
    'session.sign_out': 'Sign out',
    'session.signed_out': 'You are signed out.',
    'login.eyebrow': 'eigentliCH',
    'login.title': 'Sign in',
    'login.lede': 'Your documents and your plan sit behind your own password. Nobody else sees them.',
    'login.email': 'Email address',
    'login.password': 'Password',
    'login.submit': 'Sign in',
    'login.no_account': 'No account yet?',
    'login.register': 'Open an account',
    'login.forgotten': 'Forgotten your password? eigentliCH runs on this machine, and whoever operates it can set a new one. There is deliberately no email with a link in it.',
    'register.eyebrow': 'eigentliCH',
    'register.title': 'Open an account',
    'register.lede': 'Four details. Then you sign in with the password you have just chosen.',
    'register.name': 'What should we call you?',
    'register.name_hint': 'A name you would like to see on your own screen.',
    'register.age': 'How old are you?',
    'register.age_hint': 'From 18.',
    'register.email': 'Email address',
    'register.email_hint': 'This is what you sign in with. It stays on this machine.',
    'register.password': 'Password',
    'register.password_hint': 'At least 12 characters. Length is the only rule — composition rules produce shorter, more guessable passwords.',
    'register.submit': 'Open the account',
    'register.cancel': 'Back to signing in',
    'register.now_sign_in': 'Account opened. Sign in now.',
    'password.eyebrow': 'eigentliCH',
    'password.title': 'Choose a new password',
    'password.lede': 'This account was set up with a password that is good for the first sign-in only. Choose your own now.',
    'password.current': 'Current password',
    'password.current_hint': 'Required here too: without it a stolen session would be enough to change the password.',
    'password.new': 'New password',
    'password.new_hint': 'At least 12 characters. The current password stops working afterwards.',
    'password.repeat': 'Repeat the new password',
    'password.submit': 'Set the password',
    'password.mismatch': 'The two entries do not match.',
    'password.sign_out': 'Sign out',
    // See the German block: A40's separate door, and the `password.*` block reused for the forced change.
    'curator.door_hint': 'Do you curate for eigentliCH?',
    'curator.door': 'Go to the curator sign-in',
    'curator.eyebrow': 'eigentliCH',
    'curator.title': 'Curator sign-in',
    'curator.lede': 'Curators sign in with their own credentials, which live in their own table. This is not the member sign-in.',
    'curator.email': 'Email address',
    'curator.email_hint': 'The curator address, not the member one.',
    'curator.password': 'Password',
    'curator.submit': 'Sign in',
    'curator.back': 'Back to the member sign-in',
    'curator.sign_out': 'Sign out',
    'curator.signed_out': 'You are signed out. The credentials are gone from this window.',
    'curator.password_changed': 'The password is set. The previous one no longer works.',
    'curator.workbench_eyebrow': 'Curators',
    'curator.workbench_title': 'What has been shared with you',
    'curator.workbench_lede': 'The members who have given you sight of something, and what that sight covers.',
    'curator.identity': 'Signed in as',
    'curator.role': 'Role',
    'curator.no_role': 'No role label',
    'curator.no_token': 'No session key is issued to a curator. Your credentials stay in this window and travel with every request; after a page reload you sign in again.',
    'curator.grant_model': 'The member gives sight themselves, for named areas and for a limited time. There is no "everything" and no "until withdrawn", and the member takes it back at any moment with immediate effect.',
    'curator.nothing_granted': 'No member has given you sight of anything at the moment. That is why nothing is listed here: from this screen there is no route into material that has not been shared.',
    'curator.scope': 'Scope',
    'curator.expires': 'Ends on',
    'curator.reload': 'Ask again',
    'curator.reloaded': 'What has been shared was read again.',
    'curator.open_consultation': 'Open a consultation',
    'curator.consultation_opened': 'Consultation opened. The entry is written.',
    'curator.audit_note': 'Opening a consultation writes an entry into a log that cannot afterwards be changed or removed.',
    'curator.granted': 'Shared',
    'curator.withheld': 'Not shared',
    'curator.member': 'Member',
    'curator.refused': 'This request was refused. The reason is below, as the server wrote it.',
    'curator.scope_positions': 'Positions',
    'curator.scope_goals': 'Goals',
    'curator.scope_decisions': 'Decisions',
    'curator.scope_vault': 'Vault',
    'curator.scope_action_items': 'Prepared decisions',
    'curator.sections': 'What the member has shared',
    'curator.section_empty': 'Nothing is recorded in this area.',
    'curator.vault_no_bytes':
      'The index of the vault, without the files themselves. Sharing the vault opens the index and not '
      + 'the documents.',
    'curator.no_sections': 'No area is shared from which anything could be shown.',
    'curator.consultation': 'This consultation',
    'curator.consultation_ref': 'Consultation',
    'curator.log': 'The log of this consultation',
    'curator.log_opened': 'Opened',
    'curator.log_note': 'Note',
    'curator.log_closed': 'Closed',
    'curator.notes_redacted':
      'The wording of the notes cannot be read without a live grant. That a note was written stays '
      + 'visible.',
    'curator.note': 'Note on this consultation',
    'curator.note_hint':
      'The note is appended to the log and cannot afterwards be changed. It counts as the member\'s '
      + 'material and can only be read under a live grant.',
    'curator.note_add': 'Append the note',
    'curator.note_added': 'The note is appended.',
    'curator.note_missing': 'An empty note is not sent.',
    'curator.recommend_heading': 'Record a recommendation',
    'curator.recommend_hint':
      'A recommendation comes from the person curating and never from eigentliCH. It is recorded as a '
      + 'decision with your name on it and belongs to the member\'s record from then on.',
    'curator.recommend_question': 'What was the question?',
    'curator.recommend_choice': 'What you are recording',
    'curator.recommend_reasoning': 'Reasoning',
    'curator.recommend_submit': 'Record as a decision',
    'curator.recommend_done': 'Recorded, with your name on it.',
    'curator.recommend_missing': 'Both the question and what you are recording are needed.',
    'curator.close_heading': 'Close the consultation',
    'curator.close_hint':
      'Every consultation is closed with its outcome. It cannot be closed without one, and no outcome is '
      + 'filled in for you here.',
    'curator.close_outcome': 'Outcome',
    'curator.close_outcome_missing': 'Without an outcome nothing is sent.',
    'curator.close_note': 'Closing remark',
    'curator.close_liability': 'Flag a liability question',
    'curator.close_submit': 'Close the consultation',
    'curator.closed': 'The consultation is closed. The outcome is in the log.',
    'curator.still_open': 'Still open',
    'onboarding.eyebrow': 'First conversation',
    'onboarding.title': 'A few questions',
    'onboarding.lede': 'Only the first is needed. Anything you skip can be recorded in the grid later.',
    'onboarding.why': 'Why this question?',
    'onboarding.skip': 'Skip',
    'onboarding.next': 'Next',
    'onboarding.finish': 'Done — show the grid',
    'onboarding.saved': 'Saved.',
    // See the German block: the goal question offers the templates and fills the goal out.
    'onboarding.goal_template': 'Goal',
    'onboarding.goal_name': 'What do you call this goal?',
    'onboarding.goal_name_hint': 'The name of the template is filled in. You may overwrite it — it is your goal, not our template.',
    'nav.plan': 'Positions',
    'nav.containers': 'Goals',
    'regime.reading_crisis_tail': 'Probability of a crisis',
    'regime.reading_bimodal': 'Two possible states rather than one',
    'regime.yes': 'yes',
    'regime.no': 'no',
    'regime.title': 'The regime',
    'regime.lede': 'Where the economy stands. This page is the same for everybody and needs no account.',
    'regime.unavailable': 'No regime reading is published at the moment.',
    'regime.nothing_personal': 'Nothing here is about you. These figures are the same for everybody.',
    'regime.source': 'Where this reading comes from',
    'regime.source_regime': 'Regime',
    'regime.source_scope': 'Scope',
    'regime.source_as_of': 'As of',
    'regime.source_model': 'Model version',
    'regime.source_published_by': 'Published by',
    'feed.title': 'Reading',
    'feed.lede': 'What there is to read. Tap a topic and it becomes about your situation — only what is missing gets asked.',
    'feed.section_groups': 'Groups',
    'feed.section_follows': 'Who you follow',
    'feed.section_vaults': 'Collections',
    'feed.empty_no_gathering_is_seeded': 'Nothing here yet: no gathering is recorded.',
    'feed.empty_no_follow_relation_exists': 'Nothing here yet: following does not exist in this build.',
    'feed.empty_for_you': 'Nothing is recorded here for you.',
    'feed.tap_asks': 'Relate this to my situation',
    'feed.tap_ready': 'Relate this to my situation — nothing missing',
    'feed.ordering_note': 'Ordered as the contents are. What you have read is not recorded.',
    'network.title': 'The network',
    'network.lede': 'Who is reachable, and who would be suggested. Two separate rings.',
    'network.connected': 'Reachable',
    'network.connected_empty': 'Nobody is listed at the moment.',
    'network.suggested': 'Suggested',
    'network.suggested_empty': 'Nobody is here yet: there is no matcher to compute suggestions from. Nothing is invented here.',
    'network.role_unstated': 'Role not stated',
    'network.privacy': 'Assets, liabilities and goals are never visible here. Nothing from your Vault feeds this page.',
    'nav.regime': 'Regime',
    'nav.feed': 'Reading',
    'nav.actions': 'Actions',
    'nav.documents': 'Documents',
    'nav.befund': 'Befund',
    // `door.know_title` and `door.know_body` are removed: S-10 stands behind the Knowledge and Community
    // door now instead of a placeholder. The sentence the placeholder existed to say — the Know panel is a
    // different thing and stays on every screen — is `capabilities.know_panel_note` on the real screen,
    // where it is worth more.
    // Removed with the German pair above — see the note there.
    'know.panel': 'The Know',
    'know.open': 'Open The Know',
    'know.close': 'Close',
    'know.lede': 'Answers come from your own documents and from the learning material. What is not in those is not here either.',
    'know.ask': 'Your question',
    'know.ask_submit': 'Ask',
    'know.asking': 'Reading …',
    'know.answer': 'Answer',
    'know.unavailable': 'No answer right now',
    'know.model': 'Model',
    'know.citations': 'Drawn from',
    'know.citation_vault_item': 'From your vault',
    'know.citation_learning_unit': 'From the learning material',
    'know.citation_book_passage': 'From the book text',
    'know.citation_knowledge_entry': 'From a reviewed explainer',
    'know.citation_member_record': 'From what you recorded',
    'know.citation_computation': 'Computed from what you recorded',
    'know.citation_where': 'Where',
    'know.citation_sources': 'Sources of this explainer',
    'know.no_citations': 'Nothing in your own documents was used.',
    'know.boundary': 'eigentliCH does not answer that',
    'know.boundary_hint': 'This is not a fault and nothing has gone wrong. A recommendation for your own situation may not be produced here. A curator may discuss it with you.',
    'know.curator': 'Bring in a curator',
    'know.curator_choose': 'Who would you like to bring in?',
    'know.curator_loading': 'Fetching …',
    'know.curator_person': 'Your request goes to',
    'know.curator_directory_error': 'Who is there right now cannot be fetched at the moment. Nobody is assumed, so nothing is sent.',
    'know.curator_opened': 'Recorded, together with the screen you asked from.',
    'know.curator_from': 'Opened from',
    'know.curator_unnamed': 'No curator is named right now, so nothing is sent. An entry without a named person would be an untruth in a record that is only worth having because it is true.',
    'know.actions': 'Prepared decisions',
    'know.actions_hint': 'This list appears when you open the panel. It never announces itself.',
    'know.actions_empty': 'Nothing is waiting.',
    'know.action_due': 'Due',
    'know.action_no_due': 'No date',
    'know.action_options': 'What there is to choose between, and what follows from each:',
    'ask.label': 'Your question',
    'ask.placeholder': 'Ask something about money, pensions, or your own situation.',
    'ask.submit': 'Ask',
    'ask.asking': 'The question is running.',
    'ask.answered': 'The answer is ready.',
    'ask.failed': 'The question could not be sent.',
    'ask.sources': 'Sources',
    'ask.source_unnamed': 'Untitled',
    'ask.to_curator': 'Speak to a curator',
    'ask.start_there': 'Start there',
    'ask.caveat': 'Where this answer comes from',
    'ask.caveat_branch': 'Kind of question',
    'ask.caveat_boundary': 'Scope',
    'ask.caveat_model': 'Model',
    'ask.branch_population_fact': 'A question about the subject itself. Your own records were not read for it.',
    'ask.branch_member_situation': 'A question about your own situation. Your records were read for it.',
    'ask.branch_regulated_advice': 'A question about what to do. A person answers those here.',
    'ask.boundary_below_both': 'Nothing personal involved.',
    'ask.boundary_per_member_computation': 'Worked out from your own records.',
    'ask.boundary_regulated_advice': 'A recommendation — only through a person.',
    'know.action_source': 'This concerns a document in your vault.',
    'know.trigger_vault_expiry': 'A document expires',
    'know.trigger_plan_goal_unfunded': 'No position is assigned to a goal',
    'know.trigger_plan_goal_target_date_passed': 'The date on a goal has passed',
    'know.trigger_plan_position_unrevised': 'A position has stood unchanged for a long time',
    'know.trigger_plan_capital_type_empty': 'One kind of capital is empty',
    'know.trigger_plan_onboarding_answer_skipped': 'A question from the first conversation is open',
    'know.trigger_plan_household_confirmation_due': 'Your household has not been confirmed for over a year',
    'know.trigger_plan_household_change_inferred': 'Something suggests your household may have changed',
    'know.trigger_plan_goal_frozen_for_division': 'A shared goal is frozen for division',
    'know.about_goal': 'Concerns the goal',
    'know.about_position': 'Concerns the position',
    'know.about_capital': 'Concerns the column',
    'know.about_question': 'Concerns the question',
    'know.about_household': 'Concerns your household',
    'know.about_signal': 'Prompted by',
    'know.signal_partner_invited': 'a second person was given access to the plan',
    'know.signal_partner_removed': "a second person's access was withdrawn",
    'know.signal_goal_owner_changed': "a goal's owner changed",
    'know.signal_salary_step_change': 'an income changed in a step',
    'know.signal_dated_obligation_added': 'a new dated obligation was recorded',
    'know.about_unnamed':
      'The record this refers to could not be found in your plan, so what it refers to is not named '
      + 'here.',
    'know.error': 'The question could not be sent.',
    'vault.eyebrow': 'Vault',
    'vault.title': 'Your documents',
    'vault.lede': 'What you keep here is yours. A note counts as much as a contract, and nothing is overwritten: a new version is a new row.',
    'vault.empty': 'Nothing is kept here yet. A policy, a contract, an arrangement in the family or a note to yourself all belong here.',
    'vault.version': 'Version',
    'vault.supersedes': 'replaces an earlier version',
    'vault.expiry': 'Expires on',
    'vault.no_expiry': 'No expiry date',
    'vault.has_content': 'with a file',
    'vault.note_only': 'no file, kept as a note',
    'vault.fields': 'Details of this item',
    'vault.provenance_member': 'Stated by you',
    'vault.provenance_extraction': 'Read from the file',
    'vault.confidence': 'Confidence of the reading',
    'vault.disagreement': 'The reading arrives at a different value. Yours stands; both are shown here.',
    'vault.kind_policy': 'Policy',
    'vault.kind_statement': 'Statement',
    'vault.kind_contract': 'Contract',
    'vault.kind_note': 'Note',
    'vault.kind_arrangement': 'Arrangement',
    'vault.kind_learning': 'Learning',
    'vault.kind_other': 'Other',
    'vault.source_upload': 'Uploaded',
    'vault.source_capture': 'Captured with the camera',
    'vault.source_manual': 'Entered by hand',
    'vault.source_forward': 'Forwarding address',
    'vault.source_import': 'Brought in from elsewhere',
    'vault.intake_unavailable': 'not built yet',
    'vault.intake_note': 'Four paths, one interface. Two of them are not built. They are listed anyway, so you can see what does not exist yet.',
    'vault.add_title': 'Keep something here',
    'vault.add_name': 'Title',
    'vault.add_kind': 'Kind',
    'vault.add_kind_hint': 'A note and an arrangement stand beside a policy as equals.',
    'vault.add_file': 'File (optional)',
    'vault.add_file_hint': 'With no file it is a note, and a note is a full item.',
    'vault.add_notes': 'Text (optional)',
    'vault.add_notes_hint': 'What you want to record yourself. For a note this is the content.',
    'vault.add_expiry': 'Expiry date (optional)',
    'vault.add_expiry_hint': 'An expiry date becomes a prepared decision in The Know.',
    'vault.add_more': 'How it comes in, and which version it replaces',
    'vault.add_source': 'How does it come in?',
    'vault.add_supersedes': 'Replaces',
    'vault.add_supersedes_hint': 'The earlier version stays, and stays in the export.',
    'vault.supersedes_none': 'Nothing, it is new',
    'vault.save': 'Keep it',
    'vault.export_label': 'Everything that is yours',
    'vault.export': 'Download the full export',
    'vault.export_hint': 'In a documented format, without asking anyone.',
    'vault.export_ready': 'The file is ready.',
    'containers.eyebrow': 'Plan',
    'containers.title': 'What the money is for',
    'containers.lede': 'Goals do not divide your wealth up. The same position can carry several goals, and where it does, it says so. These are not separate accounts.',
    'containers.empty': 'No goal named yet. A goal is an intention, not an account.',
    'containers.parameters': 'The five parameters',
    'containers.param_safety': 'Safety',
    'containers.param_liquidity_need': 'How quickly available',
    'containers.param_volatility_tolerance': 'Bearable movement',
    'containers.param_horizon': 'Horizon',
    'containers.param_flexibility': 'Flexibility',
    'containers.param_unanswered': 'not answered',
    'containers.param_hint': 'In your own words. These five are stored and are not interpreted today.',
    // See the German block: a bare "amount" is the thing the owner asked "at what frequency?" about.
    'containers.target_amount': 'Target amount in CHF',
    'containers.target_amount_hint': 'One sum, not a yearly figure. Leave it empty when no figure fits — a goal without an amount is a full goal.',
    'containers.target_date': 'Target date',
    'containers.no_target_date': 'No date',
    'containers.funding': 'Carried by',
    'containers.unfunded': 'No position names this goal. That is a legitimate state.',
    // ---- the occupancy question and the property finding
    'containers.property': 'Property: what the tests say',
    'containers.property_verdict_meets': 'On the published conventions this goal can be financed.',
    'containers.property_verdict_does_not_meet': 'On the published conventions this goal cannot be financed as stated.',
    'containers.property_verdict_could_not_be_determined': 'Nothing can be said yet. What is missing is below.',
    'containers.property_question': 'Will you live in it yourself?',
    'containers.property_question_hint': 'Will you live in it yourself? That decides how much equity is required and whether pension capital may be used at all. It cannot be inferred from the goal’s name, and guessing here costs more than asking.',
    'containers.property_your_answer': 'Your answer',
    'containers.property_clear': 'Leave the question open',
    'containers.property_recorded': 'Answer recorded.',
    'containers.property_failed': 'The answer could not be recorded.',
    'containers.property_binds': 'Decided by',
    'containers.property_test_equity': 'the equity test',
    'containers.property_test_affordability': 'the affordability test',
    'containers.property_because_the_goal_does_not_say_whether_the_member_will_live_in_it': 'It is not recorded whether you will live in it yourself.',
    'containers.property_because_the_goal_names_no_amount': 'The goal names no amount.',
    'containers.property_because_no_position_is_linked_to_this_goal': 'No recorded position is linked as funding for this goal, so there is no saying which money is available for the purchase.',
    'containers.property_because_no_income_is_recorded_for_the_household': 'No income is recorded for your household, and the affordability test is computed against household income.',
    'containers.property_because_the_goal_names_an_occupancy_the_record_does_not_declare': 'The recorded occupancy is not one the published conventions declare.',
    'containers.property_because_rental_income_is_not_modelled_for_a_let_property': 'This result says nothing about affordability, and that is a decision: on a let property the rent carries most of the cost, and how conservatively a lender haircuts an expected rent is published nowhere. A figure here would be a guess.',
    'containers.property_because_the_property_conventions_are_not_approved': 'The equity and affordability conventions are not approved, so nothing is computed from them.',
    'containers.overlap_note': 'These positions do not belong to this goal. They carry it.',
    'containers.also_carries_one': 'This position also carries one other goal.',
    'containers.also_carries_many': 'This position also carries {n} other goals.',
    'containers.liquidity_immediate': 'Available immediately',
    'containers.liquidity_within_months': 'Available within months',
    'containers.liquidity_within_years': 'Available within years',
    'containers.liquidity_illiquid': 'Not reliably available',
    'containers.liquidity_unstated': 'Availability not stated',
    'containers.observations': 'What is true of this goal',
    'containers.obs_dated_but_unfunded': 'This goal has a date ({date}) and no position carrying it.',
    'containers.obs_dated_but_funding_is_illiquid': 'This goal has a date ({date}). Everything carrying it is stated as not reliably available.',
    'containers.obs_liquidity_not_stated': 'For a carrying position, how quickly it is available has not been stated. Without that there is nothing to compare.',
    'containers.obs_funding_shared_with_other_goals': 'A carrying position also carries other goals.',
    'containers.illustration_none': 'No projection.',
    'containers.illustration_no_assumption_set_published': 'No assumption set has been published, and a projection without published assumptions would be a claim.',
    'containers.add_title': 'Name a goal',
    'containers.name': 'Name',
    'containers.template': 'Template',
    'containers.template_unnamed': 'No template',
    // See the German block: the placeholder is there so no template is chosen on the member's behalf.
    'containers.template_choose': 'Please choose',
    'containers.template_purpose': 'What this template means',
    'containers.funding_select': 'Which positions carry it?',
    'containers.funding_hint': 'More than one is fine, and the same position may carry other goals too.',
    'containers.no_positions': 'You have not recorded a position yet that could carry a goal.',
    'containers.save': 'Record the goal',
    'containers.default_question': 'Record the goal {name}?',
    // ---- changing a goal after it is named. See the German block on why this says "change". ----
    'containers.edit': 'Change this goal',
    'containers.edit_title': 'Change this goal',
    'containers.edit_lede': 'What you change is recorded as a decision — together with what applied before it. The earlier decision stands and is not overwritten.',
    'containers.edit_save': 'Record the change',
    'containers.edit_cancel': 'Cancel',
    'containers.edit_unchanged': 'Nothing has changed. Change something, or cancel.',
    'containers.edit_default_question': 'Change the goal {name}?',
    'containers.edit_done': 'The change is recorded.',
    'containers.edit_clear_hint': 'Leaving a field empty here means the entry is removed.',

    // ---- R-133 / C-02: the illustration, when there IS one. See the German block. ----
    'containers.illustration_no_assumption_set_in_effect_yet': 'An assumption set is published, but none is in effect as of today.',
    'containers.illustration_the_assumption_set_publishes_no_role_profiles': 'The published assumption set carries no rates per role, and without those there is nothing to illustrate.',
    'containers.illustration_the_goal_names_no_amount': 'This goal names no amount, and an illustration needs the amount it applies to.',
    'containers.illustration_the_goal_names_no_active_funding': 'No active position carries this goal, so there is no role a rate could be read for.',
    'containers.illustration_the_funding_roles_are_not_in_the_assumption_set': 'The published assumption set carries no rates for the roles that carry this goal.',
    'containers.illustration_the_goal_is_funded_only_by_human_capital':
      'So far this goal is funded only by your own labour. The assumption set publishes no market return '
      + 'for labour, so there is no figure here. Nothing is missing from your record.',
    'containers.illustration_the_goal_is_a_property_purchase':
      'For a property purchase the amount named is the price. What has to be saved is the deposit — a '
      + 'part of it. A projection toward the price would measure against the wrong figure, so there is '
      + 'no number here.',
    'containers.excluded_heading': 'Not included',
    'containers.excluded_human_capital_carries_no_market_rate':
      'Labour carries no market return. The position stays recorded and is not counted as zero — zero '
      + 'would be the claim that a salary is expected not to move.',
    'containers.illustration_projected_on': 'Calculated on',
    'containers.illustration_heading': 'Illustration',
    'containers.illustration_lede': 'This is an illustration and not a forecast. It shows what the published rates mean for the amount you named — per role and per scenario, separately.',
    'containers.illustration_basis': 'The amount it applies to',
    'containers.illustration_basis_note': 'This is the amount you named for this goal. It is not a holding: the plan does not record what you own as a franc figure.',
    'containers.illustration_assumption_set': 'Assumption set',
    'containers.illustration_effective_from': 'In effect from',
    'containers.illustration_published_by': 'Published by',
    'containers.illustration_horizon': 'Horizon',
    'containers.illustration_horizon_one_year': 'The published rates are estimated for one year.',
    'containers.illustration_horizon_years': 'The published rates are estimated for {years} years.',
    'containers.illustration_goal_horizon': 'Your target date is {years} years away.',
    'containers.illustration_not_extended': 'The rates are not extended to your target date. A rate for one year is not the same rate compounded over several years — and eigentliCH does not compound it.',
    'containers.illustration_no_goal_date': 'This goal names no date, so there is no goal horizon standing opposite the horizon of the rates.',
    'containers.illustration_unit_annualised_decimal': 'The rates are annual figures.',
    'containers.illustration_role': 'Role',
    'containers.illustration_set_role': 'In the assumption set this role is called {name}.',
    'containers.illustration_one_position_names_role': 'One position carrying this goal has this role.',
    'containers.illustration_n_positions_name_role': 'Positions with this role carrying this goal: {n}.',
    'containers.illustration_scenario': 'Scenario',
    'containers.illustration_rate': 'Rate',
    'containers.illustration_change': 'Change in CHF',
    'containers.illustration_after': 'After, in CHF',
    'containers.illustration_probability': 'Published probability',
    'containers.illustration_probability_note': 'The probabilities stand beside the rates as published. They are not multiplied into them: which probability weights which horizon is a decision with a person answerable for it, and an average on this screen would cover that up.',
    'containers.illustration_probability_unstated': 'not published',
    'containers.scenario_crisis': 'Crisis',
    'containers.scenario_contraction': 'Contraction',
    'containers.scenario_stagnation': 'Stagnation',
    'containers.scenario_expansion': 'Expansion',
    'containers.scenario_boom': 'Boom',
    'containers.illustration_caveats': 'What holds alongside it',
    'containers.caveat_rates_hold_at_the_published_horizon_only': 'The rates hold for the horizon they were estimated at, and for no other.',
    'containers.caveat_no_blended_rate_is_published': 'No blended rate is published. What stands here is separate per role and per scenario.',
    'containers.caveat_not_in_real_terms_because_no_inflation_is_published': 'No inflation figure is published, so nothing here is stated in real terms.',
    'containers.caveat_the_amount_is_stated_by_the_member_and_is_not_a_holding': 'The amount is the one you named. It is not a holding.',
    'containers.caveat_an_illustration_and_not_a_forecast': 'This is an illustration and not a forecast.',
    'containers.illustration_no_trajectory': 'Why no trajectory over the years stands here',
    'containers.illustration_no_trajectory_lede': 'A trajectory over the years would need inputs that are not available:',

    // ---- what an engine wants and a plan does not hold. See the German block. ----
    'gap.input_W_L': 'Your human capital as an amount in francs',
    'gap.input_W_R': 'Your financial capital as an amount in francs',
    'gap.input_initial_wealth': 'Your financial capital as an amount in francs',
    'gap.input_D': 'Your debt',
    'gap.input_E': 'a quantity in the calculation model with no counterpart in your plan',
    'gap.input_annual_return': 'a rate of return as a single number',
    'gap.input_base_snapshot_id': 'a numbered baseline of your plan',
    // The `supplied_by_the_caller` half. See the German block.
    'gap.input_regime_id': 'the market conditions this estimate is to be measured against',
    'gap.input_horizon_years': 'the span to calculate over — a goal with a date states it',
    'gap.input_target': 'the amount to calculate toward — a goal with an amount states it',
    'gap.input_field': 'what the "what if" question changes',
    'gap.input_to_value': 'what it changes to',
    'gap.kind_not_in_the_plan': 'your plan does not record this',
    'gap.kind_needs_an_unpublished_assumption': 'this needs an assumption eigentliCH has published',
    'gap.kind_supplied_by_the_caller': 'this belongs to the request rather than to the plan',

    // ---- the Befund: the standing report a member can read. See the German block. ----
    'befund.eyebrow': 'Report',
    'befund.title': 'Your report',
    'befund.lede': 'This report sets down what you have recorded, and what follows from it. It projects nothing forward, and it grades nothing.',
    'befund.on_request': 'It is written in the moment you open it. It is not sent to anyone, not reported anywhere, and not produced in the background.',
    'befund.as_of': 'As of',
    'befund.print': 'Print',
    'befund.announced': 'The report is loaded.',
    'befund.assumptions': 'Assumptions',
    'befund.assumption_set': 'Assumption set',
    'befund.empty_section': 'Nothing stands in this section today.',
    'befund.model_wrote': 'This sentence was rephrased by the language model.',
    'befund.computed_sentence': 'Computed sentence',
    'befund.quoted_goal_name': 'Goal',
    'befund.quoted_position_labels': 'Positions',
    'befund.quoted_question': 'Question',
    'befund.quoted_choice': 'Choice',
    'befund.quoted_reasoning': 'Reasoning',
    'befund.quoted_title': 'Document',
    'befund.quoted_prepared_options': 'Options and their consequences',

    // ---- R-301: asking for an engine run, and waiting honestly ----
    'nav.runs': 'Calculations',
    'runs.eyebrow': 'Plan',
    'runs.title': 'Ask for a calculation',
    'runs.lede': 'A calculation model reads what your plan records and works something out from it. You supply nothing for it: the inputs come from the positions and goals you recorded. A calculation changes nothing in the plan.',
    'runs.lede_wait': 'A model is allowed to take a long time — one of them up to half an hour. This screen asks again at intervals and says so while it is still working.',
    'runs.engine': 'Calculation model',
    'runs.engine_choose': 'Please choose',
    'runs.engine_market_signal': 'Market conditions',
    'runs.engine_return_estimation': 'Return estimation',
    'runs.engine_s_curve_trajectory': 'Trajectory over the years',
    'runs.engine_life_balance_sheet': 'Life balance sheet',
    'runs.engine_scenario_generator': 'What if',
    'runs.goal': 'About which goal? Optional.',
    'runs.goal_none': 'Not about a particular goal',
    'runs.submit': 'Ask for the calculation',
    'runs.list_heading': 'Calculations you asked for',
    'runs.none_yet': 'You have not asked for a calculation yet. Each one you ask for would stand here, with whatever came back.',
    'runs.announced': 'The calculations are loaded.',
    'runs.status_submitted': 'Submitted',
    'runs.status_running': 'Running',
    'runs.status_done': 'Finished',
    'runs.status_failed': 'Not available',
    'runs.submitted_at': 'Asked for',
    'runs.started_at': 'Started',
    'runs.finished_at': 'Ended',
    'runs.budget_minutes': 'Up to {minutes} minutes are allowed for this model.',
    'runs.budget_seconds': 'Up to {seconds} seconds are allowed for this model.',
    'runs.still_working': 'Still working. This screen keeps asking.',
    'runs.elapsed': 'Under way for {clock}.',
    'runs.last_checked': 'Last asked at {time}.',
    'runs.check_failed': 'The last check did not get through. This screen keeps trying.',
    'runs.took': 'It ran for {seconds} seconds.',
    'runs.result_heading': 'What came back',
    'runs.unavailable_lede': 'This model returned no answer. No figure stands with it — a figure from a run that did not finish would not be a measurement.',
    'runs.reason': 'Reason',
    'runs.refused_heading': 'This calculation was not asked for',
    'runs.refused_the_plan_does_not_answer_this_engine': 'Your plan does not record what this model needs.',
    'runs.refused_requires_an_input_the_member_did_not_supply': 'This model needs an input that belongs to a request rather than to the plan.',
    'runs.refused_requires_a_curator': 'This model ranks investment products. That is not something eigentliCH tells you.',
    'runs.refused_unknown_engine': 'There is no model by that name.',
    'runs.gaps_heading': 'What is missing for it',
    'runs.announced_queued': 'The calculation has been asked for.',
    'runs.announced_running': 'The calculation is running.',
    'runs.announced_done': 'The calculation has finished.',
    'runs.announced_failed': 'The calculation returned no answer.',
    'runs.announced_refused': 'The calculation was not asked for.',

    // ---- S-07: the decisions (R-160 to R-162) ----
    //
    // R-162 lives in the wording: the control says "record a correction" and never "edit". A decision is
    // not changed — a new entry is written referring to the earlier one, and the earlier one stands
    // untouched. Anybody reading "edit" expects the opposite.
    //
    // C-07: no number of decisions appears here. S-07 is precisely the screen a completion figure would
    // ruin.
    'decisions.eyebrow': 'Record',
    'decisions.title': 'Your decisions',
    'decisions.lede':
      'Every change to your plan stands here with the question that arose and your own reasoning. '
      + 'These entries remain, including through a change of adviser.',
    'decisions.nav': 'Decisions',
    'decisions.newest_first': 'Newest first.',
    'decisions.recorded_on': 'Recorded on',
    'decisions.author_member': 'Recorded by you.',
    'decisions.author_curator': 'Recorded by a curator.',
    'decisions.author_system': 'Recorded by eigentliCH.',
    'decisions.curator_involved': 'A curator was involved.',
    'decisions.curator_ref': 'Curator',
    'decisions.is_correction': 'This is a correction of an earlier entry.',
    'decisions.was_corrected': 'A correction of this entry was recorded later.',
    'decisions.quoted_question': 'The question',
    'decisions.quoted_choice': 'Your choice',
    'decisions.quoted_reasoning': 'Your reasoning',
    'decisions.quoted_options_considered': 'Options weighed',
    'decisions.open': 'Look at this entry',
    'decisions.back': 'Back to the list',
    'decisions.linked_heading': 'What this entry touched',
    'decisions.linked_positions': 'Positions',
    'decisions.linked_goals': 'Goals',
    'decisions.linked_vault_items': 'Documents',
    // C-04: a vault item id travels without its title and without its kind. The whole document is K3, and
    // naming even its kind here would lift this response from K2 to K3. The Befund makes the same call.
    'decisions.vault_item_id_only':
      'For documents only the id stands here. The title and the kind belong to the document itself and '
      + 'are in the vault.',
    'decisions.chain_heading': 'How this entry has stood',
    'decisions.chain_oldest_first': 'Oldest entry first.',
    'decisions.chain_this_one': 'This entry',
    'decisions.chain_single': 'No correction of this entry has been recorded.',
    // R-162, verbatim. Never "edit".
    'decisions.correct': 'Record a correction',
    'decisions.correct_heading': 'Record a correction',
    'decisions.correct_hint':
      'The earlier entry stands untouched. A new entry is written referring to it. The question stays the '
      + 'same — it is part of what was recorded at the time.',
    'decisions.correct_choice': 'What stands now?',
    'decisions.correct_reasoning': 'Reasoning (optional)',
    'decisions.correct_save': 'Record a correction',
    'decisions.correct_cancel': 'Cancel',
    'decisions.correct_choice_missing': 'Please record what stands now. An empty entry would stay empty.',
    'decisions.corrected': 'The correction is recorded.',
    'decisions.filter_heading': 'Narrowed to',
    'decisions.filter_position': 'Position',
    'decisions.filter_goal': 'Goal',
    'decisions.filter_vault_item': 'Document',
    'decisions.filter_clear': 'Remove the filter',
    'decisions.filtered_none':
      'No entry is recorded for this filter. Without it the other entries still stand.',
    'decisions.announced': 'The decisions are loaded.',
    'decisions.announced_one': 'The entry is loaded.',

    // ---- R-103: consent at registration ----
    //
    // The wording comes entirely from the server (`GET /api/consent-statement`) and is not re-authored
    // here. What is here is the surround: the heading, the boxes, the refusal.
    'consent.heading': 'What eigentliCH does with what you enter',
    'consent.lede':
      'Before an account exists, this says what happens to what you enter. The wording comes from the '
      + 'server and is shown here unchanged.',
    'consent.provisional':
      'This wording is provisional. These are honest descriptions of what eigentliCH does, and they are not '
      + 'a data-protection notice — nobody qualified has reviewed them.',
    'consent.agree': 'I agree to the text above.',
    'consent.required': 'No account is opened without this agreement.',
    // ---- Notices: not a choice, and therefore not a checkbox ----
    //
    // `entscheidprotokoll` is a notice rather than a consent. Keeping the record belongs to the service,
    // cannot be declined, and the entry cannot be removed afterwards — so a member is told rather than
    // asked. There is deliberately no "I have read this" here: an acknowledgement that records nothing
    // would look like a choice that does not exist.
    'consent.notice_kind': 'Notice',
    'consent.notice_only':
      'This is a notice rather than a consent. There is nothing to tick: keeping the record belongs to the '
      + 'service and cannot be declined, so you are told about it.',
    // C-07 caught "points" here a second time — same forbidden list, same hour, a different sentence.
    'consent.notices_are_not_a_choice':
      'Not everything below is asking you something. Some of it is a notice: you are told about it because '
      + 'it belongs to the service — not offered as a choice, and not withdrawable.',
    'consent.consequence_consent': 'What withdrawing would mean',
    'consent.consequence_notice': 'Why this is not a choice',
    'consent.version': 'Version',
    // C-07 caught a real word here: the first draft said "the required points", and "points" is on the
    // forbidden list — found by the filter rather than by reading it (A88).
    'consent.missing':
      'Please agree where agreement is required. eigentliCH does not open an account without it, and none '
      + 'is created either.',
    'consent.unavailable':
      'The wording could not be loaded. The form is not sent without it: agreement to text that was never '
      + 'shown would not be agreement.',
    'consent.retry': 'Load again',

    // ---- R-230: seeing and withdrawing consent ----
    'consents.eyebrow': 'Settings',
    'consents.heading': 'Your consents',
    'consents.lede':
      'Every consent you have given, with the version of the wording that was shown at the time. '
      + 'Withdrawn ones stay in the list.',
    'consents.granted_at': 'Agreed on',
    'consents.withdrawn_at': 'Withdrawn on',
    'consents.standing': 'Stands.',
    'consents.withdrawn': 'Withdrawn.',
    'consents.required':
      'No account is opened without this consent. Withdrawing it has no effect of its own on an account '
      + 'that already exists.',
    // The label follows `kind`, because the field is named the same for both (`consequence`) and for one it
    // means "withdrawal" while for the other it means "there is no withdrawing".
    'consents.consequence_consent': 'What withdrawing means',
    'consents.consequence_notice': 'Why this is not a choice',
    // A row from the time eigentliCH still asked for agreement to this. It stays visible — R-230 asks exactly
    // that question — and no control stands beside it.
    'consents.notice_row':
      'Agreement to this is no longer asked for; you are told about it instead. Your agreement at the time '
      + 'stays visible, and there is nothing in it to withdraw.',
    // **Not the word "Withdraw" on its own**, and C-01 is the reason rather than style. Rule 2's opening
    // verb list contains `withdraw`, so a bare imperative "Withdraw" is refused by the outbound gate as a
    // directive — and it is right to: on its own the word does not say whose consent, or that the entry
    // stays. Found by the gate running over the whole string table, not by reading the label.
    'consents.withdraw': 'Record a withdrawal',
    'consents.withdraw_confirm': 'Confirm the withdrawal',
    'consents.withdraw_cancel': 'Cancel',
    // Said out loud, because a screen would otherwise offer "remove from list".
    'consents.marks_not_deletes':
      'A withdrawal is marked, it deletes nothing. The entry stays, with the date it was withdrawn.',
    'consents.withdrawn_announced': 'The withdrawal is recorded.',
    'consents.purpose_datenbearbeitung': 'Processing what you enter',
    'consents.purpose_entscheidprotokoll': 'The record of decisions',
    'consents.purpose_kuratoren_zugriff': 'Access by curators',
    'consents.retired_purpose':
      'Consent to this point is no longer asked for. What you agreed to at the time still stands here.',

    // ---- Notices on the settings screen ----
    //
    // Not a footnote. Every member gets these regardless of any recorded row, and the more surprising of
    // the two facts is in them: a recorded decision cannot be deleted, by anyone, eigentliCH included, and
    // survives an erasure emptied of name and text.
    'notices.heading': 'What eigentliCH tells you',
    'notices.lede':
      'The following belongs to the service. You are told about it rather than asked — there is nothing to '
      + 'tick here and nothing to withdraw.',
    'notices.kind': 'Notice',
    'notices.consequence': 'Why this is not a choice',

    // ---- Settings: the screen itself ----
    'settings.eyebrow': 'Settings',
    'settings.title': 'Settings',
    'settings.lede': 'Your consents, your data, and the way out.',
    'settings.nav': 'Settings',
    'settings.export_heading': 'Get all your data',
    'settings.export_hint':
      'You get a file with everything eigentliCH has recorded about you — including the deposited documents '
      + 'and their content. That you asked for it is recorded as a decision.',
    'settings.export': 'Ask for the file',
    'settings.export_ready': 'The file is ready.',
    'settings.export_decision': 'Recorded as a decision',
    'settings.export_working': 'The file is being assembled.',

    // ---- R-231: erasure ----
    //
    // Two steps, and the first is a door somebody has to open. The way there is deliberately not
    // convenient: there is no way back.
    'erasure.heading': 'Delete the account and the data',
    'erasure.hint':
      'This deletes your account and what you have entered. Afterwards there is no way back and no copy '
      + 'at eigentliCH from which anything could be restored.',
    'erasure.open': 'Prepare the deletion',
    'erasure.close': 'Do not delete',
    'erasure.title': 'Delete the account and the data',
    'erasure.irreversible': 'This step is final.',
    'erasure.what_goes':
      'Deleted: your account, your credentials, your positions, your goals, your answers, your documents '
      + 'including their files, and your sessions.',
    'erasure.what_stays_heading': 'What remains',
    'erasure.what_stays':
      'The recorded decisions and the log of a curator session remain as rows. They are emptied: your name '
      + 'and your text are removed and the link to you is severed. Those rows cannot be removed at the '
      + 'storage layer, not by you and not by eigentliCH.',
    'erasure.phrase_label': 'Type exactly this sentence to confirm',
    'erasure.phrase_hint': 'Word for word, in capitals. Copying it is fine.',
    'erasure.password_label': 'Your password',
    'erasure.password_hint':
      'In addition to the sentence. An open session on a borrowed laptop must not be enough to destroy a '
      + 'record.',
    'erasure.reason_label': 'Reason (optional)',
    'erasure.reason_hint':
      'Recorded on the decision that registers the deletion — and removed again by the deletion itself.',
    'erasure.submit': 'Delete it all now',
    'erasure.phrase_missing': 'Please type the sentence exactly as it stands above.',
    'erasure.password_missing': 'Please enter your password.',
    'erasure.done_heading': 'Deleted',
    'erasure.done_lede':
      'Your account is deleted and this session has ended. What stands here is the receipt — it goes when '
      + 'you leave this page.',
    'erasure.done_deleted': 'Removed',
    'erasure.done_redacted': 'Emptied',
    'erasure.done_decision': 'The decision recording the deletion',
    'erasure.done_announced': 'The account is deleted. The session has ended.',
    'erasure.rows': 'rows',

    // ---- S-10: capabilities (D-01 / R-194) ----
    //
    // D-01 is answered: a capability is the member's own self-assessment. eigentliCH does not test, grade or
    // certify one. So there is no word here that implies assessment — no rung, no test, no certificate.
    'capabilities.eyebrow': 'Knowledge & community',
    'capabilities.title': 'What you can do',
    'capabilities.lede':
      'These sentences describe what somebody can say about their own figures after working through the '
      + 'learning units. You record which of them hold for you.',
    'capabilities.self_assessed':
      'This is your own assessment. eigentliCH does not check it, does not grade it and certifies nothing. '
      + 'There is no order and there are no rungs — each sentence stands on its own.',
    'capabilities.no_qualification':
      'eigentliCH claims no official or accredited standing and issues no certificate.',
    'capabilities.fictional':
      'The sentences and the learning units are invented for this build and have not been reviewed '
      + 'editorially.',
    'capabilities.asserted': 'Recorded by you.',
    'capabilities.asserted_on': 'Recorded on',
    'capabilities.assert': 'This holds for me',
    'capabilities.assert_heading': 'Record it yourself',
    'capabilities.assert_hint':
      'You record that this sentence holds for you. It is your statement about yourself.',
    'capabilities.evidence_unit_label': 'A learning unit you worked through (optional)',
    'capabilities.evidence_unit_hint':
      'Only units whose content evidences this exact sentence are offered here. Without one your statement '
      + 'stands on its own.',
    'capabilities.evidence_unit_none': 'Name none',
    'capabilities.evidence_unit': 'Learning unit',
    'capabilities.evidence_self': 'Your own statement, with no reference to a learning unit.',
    'capabilities.assert_save': 'Record it',
    'capabilities.assert_cancel': 'Cancel',
    'capabilities.asserted_announced': 'Recorded.',
    'capabilities.already': 'That is already recorded.',
    'capabilities.no_removal':
      'A recorded sentence cannot be taken back here. What a withdrawal would mean for an offer resting on '
      + 'it is not decided — and a form is the wrong place to answer that question.',
    'capabilities.units_heading': 'The learning units for it',
    'capabilities.announced': 'The capabilities are loaded.',
    'capabilities.know_panel_note':
      'The knowledge panel at the right-hand edge is a different thing and stays with you on every screen.',

    // ---- R-122 / R-123: changing a position ----
    'position.edit': 'Change the position',
    'position.edit_title': 'Change the position',
    'position.edit_hint':
      'The position is changed and the earlier state recorded as a decision. Both states stand in that '
      + 'entry.',
    'position.edit_save': 'Record the change',
    'position.edit_unchanged':
      'Nothing is changed. A decision asserting a change that did not happen stands permanently, so it is '
      + 'not written.',
    'position.edit_liquidity': 'Availability',
    'position.edit_liquidity_hint':
      'One of the four bands, never a number of years: a threshold in years would be an assumption, and '
      + 'nobody has published one. What stands here is the band already recorded.',
    // A99 put `liquidity` into the overview payload, so the first option now reads "not stated" rather
    // than "leave unchanged": the band already recorded is preselected, and "not stated" is a value that
    // can be chosen again.
    'position.liquidity_choose': 'Not stated',
    'position.liquidity_immediate': 'Available at once',
    'position.liquidity_within_months': 'Available within months',
    'position.liquidity_within_years': 'Available within years',
    'position.liquidity_illiquid': 'Not freely available',
    // R-122 has its own control, and that is not caution: a tick-box in the middle of an edit form is the
    // way a position gets stood down by accident.
    'position.deactivate': 'Take out of the live plan',
    'position.deactivate_heading': 'Take out of the live plan',
    'position.deactivate_hint':
      'This position then no longer counts in the Befund, the illustration stops projecting it, and the '
      + 'derivations leave it out.',
    'position.deactivate_stays':
      'Nothing is deleted. The position stays in the overview marked as no longer active and stays linked '
      + 'to every decision that mentions it.',
    'position.deactivate_save': 'Stand it down',
    'position.reactivate': 'Back into the live plan',
    'position.reactivate_heading': 'Back into the live plan',
    'position.reactivate_hint':
      'This position then counts in the Befund again, and the illustration projects it again.',
    'position.reactivate_save': 'Take it back',
    'position.status_cancel': 'Cancel',
    'position.deactivated_announced': 'The position is stood down. It still stands in the overview.',
    'position.reactivated_announced': 'The position is back in the live plan.',
    'position.changed_announced': 'The change is recorded.',
    'position.decision_heading': 'What are we recording?',
    'position.decision_hint':
      'This change is recorded with its reasoning too. It stays your own record.',
    'position.see_decisions': 'Decisions about this position',

    'error.load': 'The positions could not be loaded.',
    'error.detail': 'Reason',

    // ================================================================================================
    // R-210 / R-213 — granting a curator access, and taking it away
    // ================================================================================================
    'grants.nav': 'Curator access',
    'grants.eyebrow': 'Your decision',
    'grants.title': 'Curator access',
    'grants.lede':
      'This is who may see something of yours, which areas that covers, and until when. Without an open '
      + 'grant a curator sees nothing of yours — not even when a consultation has already been opened.',
    'grants.scoped': 'A grant names individual areas. There is no setting that opens everything.',
    'grants.time_limited': 'A grant ends at a fixed time. There is no grant without an end.',
    'grants.immediate':
      'A grant you withdraw is closed from that moment. The next request that person makes is refused.',
    'grants.no_pending':
      'There is no intermediate state: no waiting period, no approval by anyone else, and nothing to '
      + 'confirm afterwards.',
    'grants.no_blanket_access':
      'The server has neither a blanket grant nor a grant that runs until further notice.',
    'grants.scopes_label': 'Areas opened',
    'grants.scope_positions': 'Positions',
    'grants.scope_positions_covers': 'What you have recorded, across both kinds of capital.',
    'grants.scope_goals': 'Goals',
    'grants.scope_goals_covers':
      'What you are working toward, with the amount and the period where you have named one.',
    'grants.scope_decisions': 'Decisions',
    'grants.scope_decisions_covers':
      'Your own record: which question arose, how you decided, and why.',
    'grants.scope_vault': 'Documents',
    'grants.scope_vault_covers':
      'The documents you have deposited. This is the most sensitive of the four classes in the whole store.',
    'grants.scope_action_items': 'Prepared decisions',
    'grants.scope_action_items_covers': 'What is prepared for you in The Know.',
    'grants.granted_at': 'Granted',
    'grants.expires_at': 'Ends',
    'grants.revoked_at': 'Withdrawn',
    'grants.open_heading': 'Open grants',
    'grants.none_open':
      'No grant is open at the moment. Once you make one it stands here with the areas it opens and the '
      + 'date it ends.',
    'grants.ended_heading': 'Grants that have ended',
    'grants.ended_hint':
      'These grants are closed. They stay visible because the record that they existed stays.',
    'grants.ended_withdrawn': 'You withdrew this grant.',
    'grants.ended_lapsed': 'This grant has lapsed.',
    'grants.record_kept':
      'The access is closed. The record that it existed stays and is not deleted.',
    // **Not "Withdraw access", and the reason is C-01 rather than style.** A clause-initial `withdraw` is
    // in `_DIRECTIVE_FORCE`, so `check_answer` refuses the phrase — correctly, by its own rules: it cannot
    // tell a button on the member's own consent screen from an instruction to move money. A78 and A95 both
    // record the same shape, and the answer both times was to reword the copy rather than to weaken the
    // gate. `revoke` is R-213's own verb and is not a verb of moving money, so nothing is lost.
    'grants.revoke': 'Revoke access',
    'grants.revoke_hint': 'Takes effect at once. The next request that person makes is refused.',
    'grants.revoked_announced': 'The access is withdrawn.',
    'grants.curator_unnamed': 'Not in the directory',
    'grants.curator_not_in_directory':
      'This person is not in the directory of curators a member can ask for. What is shown is the '
      + 'reference the grant carries; no name is invented here.',
    'grants.new_open': 'Grant access',
    'grants.new_heading': 'Grant new access',
    'grants.new_hint': 'Three answers: who, which areas, until when. None of them is preselected.',
    'grants.choose_curator': 'Who may see something?',
    'grants.choose_curator_none': 'Please choose',
    'grants.choose_curator_hint': 'The directory names the curators a member can ask for.',
    'grants.no_curators':
      'The directory names nobody at the moment. Without a named person there is no grant to make.',
    'grants.choose_scopes': 'Which areas?',
    'grants.choose_scopes_hint':
      'This list comes from the server. An area not ticked here stays closed.',
    'grants.choose_window': 'Until when?',
    'grants.choose_window_none': 'Please choose',
    'grants.choose_window_hint': 'Every grant ends. A grant without an end is not provided for.',
    'grants.window_one_hour': 'One hour',
    'grants.window_hours': '{n} hours',
    'grants.window_one_day': 'One day',
    'grants.window_days': '{n} days',
    'grants.window_usual': 'the usual window',
    'grants.submit': 'Grant access',
    'grants.granted_announced': 'The access is granted.',
    'grants.no_curator_chosen': 'No person is chosen yet.',
    'grants.no_scope_chosen': 'No area is ticked yet. A grant with no area opens nothing.',
    'grants.no_window_chosen': 'No window is chosen yet.',
    'grants.announced': 'Curator access loaded.',
    'know.curator_sees_nothing':
      'The consultation is recorded. Nothing is shared by it: without a grant this person sees none of '
      + 'your material.',
    'settings.grants_heading': 'Curator access',
    'settings.grants_lede':
      'Who may see something of yours, which areas that covers, and until when. A withdrawal takes '
      + 'effect at once.',

    // ================================================================================================
    // S-11 — the Market Place
    // ================================================================================================
    'market.eyebrow': 'Market place',
    'market.title': 'Market place',
    'market.lede':
      'Offers are ordered by the four roles, not by profession. Suppliers and members offers stand '
      + 'alongside one another in one list.',
    'market.not_gated':
      'Reading and getting in touch are not conditional on anything. There is nothing here to unlock.',
    'market.fictional_all': 'The suppliers and offers in this list are invented.',
    'market.filter_heading': 'Filter',
    'market.filter_from_grid': 'The list is narrowed to the roles that appear in your plan.',
    'market.filter_chosen': 'The list is narrowed to the roles you chose.',
    'market.filter_removed': 'The filter is off. The list shows all roles.',
    'market.filter_grid_empty': 'Your plan names no role yet, so nothing is narrowed.',
    'market.filter_none': 'No filter is set.',
    'market.filter_remove': 'Remove the filter',
    'market.ordering_heading': 'Order',
    'market.ordering_not_for_sale':
      'The order of this list cannot be bought. It is formed from three inputs and from nothing else.',
    'market.ordering_input_role_match': 'Match with the roles asked for',
    'market.ordering_input_capability_evidence': 'Recorded capabilities',
    'market.ordering_input_community_presence': 'Presence in the community',
    'market.ordering_share':
      'The match counts as a share of what an entry declares about itself. Declaring many roles gains '
      + 'nothing.',
    'market.no_qualification':
      'eigentliCH awards no qualification and verifies none. Registration references belong to the '
      + 'supplier who supplied them.',
    'market.kind_provider_listing': 'Supplier',
    'market.kind_member_offer': 'A member offer',
    'market.roles_label': 'Roles',
    'market.domain_label': 'Area',
    'market.domain_financial': 'Finance',
    'market.domain_health': 'Health',
    'market.domain_education': 'Education',
    'market.pipeline_label': 'How it is evidenced',
    'market.pipeline_capability': 'Recorded capabilities',
    'market.pipeline_professional_registration': 'Professional registration',
    'market.registration_refs_label': 'Registration references',
    'market.registration_refs_own':
      'These references come from the supplier itself. eigentliCH has not checked them.',
    'market.supplier_label': 'Supplier',
    'market.contact_heading': 'Contact',
    'market.contact_not_gated': 'Getting in touch is not conditional on anything.',
    'market.contact_offer': 'Show how to get in touch',
    'market.contact_via_member':
      'A member offer is reached through the member. So there is no address there, only a reference.',
    'market.disclosures_heading': 'Disclosures',
    'market.disclosures_absent':
      'This entry names no disclosure. That should not happen: an entry reaches the market place only '
      + 'through the disclosure.',
    'market.disclosure_declared_by': 'Declared by',
    'market.disclosure_none_declared': 'Nothing to declare',
    'market.disclosure_commission_from_third_party': 'Payment from a third party',
    'market.disclosure_own_working_document': 'Its own working document',
    'market.disclosure_referral_arrangement': 'Referral arrangement',
    'market.disclosure_shared_ownership': 'Shared ownership',
    'market.offer_kind_co_investment': 'Investing together',
    'market.offer_kind_succession': 'Succession',
    'market.offer_kind_property': 'Property',
    'market.offer_kind_skills': 'Skills',
    'market.offer_kind_services': 'Services',
    'market.direction_offer': 'on offer',
    'market.direction_search': 'sought',
    'market.fictional': 'An invented entry.',
    // Not "Open the entry", for the same reason as `grants.revoke` above: a clause-initial `open` is in
    // C-01's directive lexicon. The German imperative form is not, so only this side is reworded.
    'market.open_listing': 'Show the entry',
    'market.back': 'Back to the list',
    'market.no_entries':
      'There is no entry in the market place for these roles at the moment. Suppliers and members '
      + 'offers would stand here alongside one another.',
    'market.status_label': 'State',
    'market.status_draft': 'Draft',
    'market.status_published': 'In the market place',
    'market.announced': 'Market place loaded.',
    'market.announced_one': 'Entry loaded.',
    'market.apply_open': 'Appear as an offer yourself',
    'market.apply_heading': 'Appear as an offer yourself',
    'market.apply_lede':
      'An entry in the market place is a statement about yourself: what you offer, which roles it '
      + 'appears under, and how the entry is evidenced.',
    'market.apply_only_gate':
      'This is the only act on this page with a condition. Reading and getting in touch have none.',
    'market.apply_display_name': 'Under which name should the entry appear?',
    'market.apply_title': 'Title of the entry',
    'market.apply_summary': 'Short description (optional)',
    'market.apply_contact': 'Contact details (optional)',
    'market.apply_domain': 'Area',
    'market.apply_domain_choose': 'Please choose',
    'market.apply_domain_hint':
      'The areas offered are the ones the market place carries today. The area settles how the entry is '
      + 'evidenced.',
    'market.apply_gate_capability': 'evidenced by a capability you have recorded yourself',
    'market.apply_gate_registration': 'evidenced by a professional registration',
    'market.apply_roles': 'Roles the entry appears under',
    'market.apply_roles_hint':
      'An entry can stand under several roles. Declaring more roles does not improve the order.',
    'market.apply_refs': 'Registration references',
    'market.apply_refs_hint':
      'Separate several with a comma. They come from you; eigentliCH does not check them.',
    'market.apply_submit': 'Submit the entry',
    'market.apply_no_domain': 'No area is chosen yet.',
    'market.apply_no_role': 'No role is ticked yet.',
    'market.applied_announced': 'The draft is created.',
    'market.draft_heading': 'Draft',
    'market.draft_not_listed': 'This draft is not in the market place yet.',
    'market.draft_only_here':
      'The draft is reachable from this view and from nowhere else: there is no list of your own drafts, '
      + 'and after a page reload its reference can no longer be found.',
    'market.draft_needs_disclosure':
      'Before the entry can appear it needs at least one disclosure.',
    'market.disclosure_kind': 'Kind of disclosure',
    'market.disclosure_kind_choose': 'Please choose',
    'market.disclosure_kind_hint':
      'Declaring that there is nothing to declare is also a disclosure. An empty field is not one.',
    'market.disclosure_statement': 'Wording of the disclosure',
    'market.disclosure_add': 'Record the disclosure',
    'market.disclosure_recorded': 'The disclosure is recorded.',
    'market.disclosure_missing_fields': 'The kind and the wording are both needed.',
    'market.publish': 'Publish the entry',
    'market.published_announced': 'The entry is published.',

    // ================================================================================================
    // S-05 — the stage map
    // ================================================================================================
    'stages.nav': 'Stages',
    'stages.eyebrow': 'Plan',
    'stages.title': 'Stages',
    'stages.lede':
      'Five situations that occur in a life, and the questions they raise. No grading and no sequence '
      + 'you would have to work through.',
    // D-07. See the German above: the lead-in lives here, the phrase does not.
    'stages.destination_lead': 'What all of this leads to: ',
    'stages.all_open': 'You can open any of these situations, whatever your age.',
    'stages.not_a_position':
      'The map opens at one place. That is not a statement about where you stand.',
    'stages.age_marker': 'Age at which this situation typically arrives',
    'stages.age_marker_not_a_condition':
      'This number is not a condition of entry and is never compared with your own age.',
    'stages.questions': 'Questions this situation raises',
    'stages.opens_here': 'The map opens here.',
    'stages.draft_wording': 'Wording not yet read',
    'stages.no_stage_after': 'No further situation follows {age}.',
    'stages.no_stage_after_reason':
      'Living from assets, capital against an annuity and the timing of the AHV draw are deliberately '
      + 'out of scope. That is a decision, not an omission.',
    'stages.announced': 'Stages loaded.',

    // ================================================================================================
    // S-09 — the life-event modules. R-222: this is where the word events applies.
    // ================================================================================================
    'life_events.nav': 'Life events',
    'life_events.eyebrow': 'Plan',
    'life_events.title': 'Life events',
    'life_events.lede':
      'Seven situations in which things move quickly. The frame is here; the content is not written yet.',
    'life_events.none_written': 'None of the seven modules has its content written.',
    'life_events.not_written': 'The content of this module is not written yet.',
    'life_events.not_written_why':
      'This content is written by people rather than generated. So what stands here is the frame, and '
      + 'not text nobody could answer for.',
    'life_events.frame_heading': 'What every module will hold',
    'life_events.first_steps': 'First steps',
    'life_events.do_not_sign': 'What is not signed now',
    'life_events.vault_kinds': 'Which documents count here',
    'life_events.curator_role': 'What a curator does here',
    'life_events.field_unwritten': 'Not written yet.',
    'life_events.vault_kinds_unwritten': 'Not settled yet.',
    'life_events.retrieval_unavailable':
      'No document was looked for, because this module does not yet settle which kinds count here. That '
      + 'is a different thing from an empty store.',
    'life_events.your_documents': 'Your documents for this',
    'life_events.no_documents': 'You have deposited no document of these kinds.',
    'life_events.expires': 'Expires',
    'life_events.authored_by': 'Written by',
    'life_events.open': 'Open the module',
    'life_events.back': 'Back to the list',
    'life_events.announced': 'Life events loaded.',
    'life_events.announced_one': 'Module loaded.',
    'life_events.module_separation': 'Separation',
    'life_events.module_job_loss': 'Loss of a job',
    'life_events.module_illness_and_incapacity': 'Illness and incapacity',
    'life_events.module_death_of_a_partner': 'Death of a partner',
    'life_events.module_inheritance': 'Inheritance',
    'life_events.module_caring_for_parents': 'Caring for parents',
    'life_events.module_move_abroad_or_return': 'Moving abroad, or returning',

    // ================================================================================================
    // S-13 — lectures and meet-ups. R-222: none of these words is event.
    // ================================================================================================
    'community.nav': 'Community',
    'community.eyebrow': 'Community',
    'community.title': 'Lectures and meet-ups',
    'community.lede': 'What is scheduled, and where you were there.',
    'community.not_a_standing':
      'Your attendance is recorded and not counted. It is one of three inputs the order in the market '
      + 'place is formed from, and it is not a judgement about you.',
    'community.kind_lecture': 'Lecture',
    'community.kind_cafe_evening': 'Cafe evening',
    'community.kind_meetup': 'Meet-up',
    'community.held_on': 'Date',
    'community.location': 'Place',
    'community.you_were_there': 'You were there.',
    'community.was_there': 'I was there',
    'community.recorded_announced': 'Your attendance is recorded.',
    'community.none_scheduled':
      'Nothing is scheduled at the moment. Lectures, cafe evenings and meet-ups would stand here with '
      + 'their date and place.',
    'community.who_schedules':
      'eigentliCH schedules these. There is deliberately no form here for a member to add one.',
    'community.fictional': 'An invented entry.',
    'community.announced': 'Lectures and meet-ups loaded.',

    // ================================================================================================
    // S-10 — the learning path
    // ================================================================================================
    'capabilities.nav': 'Capabilities',
    'learning.nav': 'Learning path',
    'learning.eyebrow': 'Knowledge',
    'learning.title': 'Learning path',
    'learning.lede': 'What there is to learn, what each unit evidences, and where that leads.',
    'learning.no_scheme': 'There is no scheme of stages. Not one still open — none.',
    'learning.not_gated': 'No unit is locked.',
    'learning.unordered': 'The sequence of this list is not a sequence to work through.',
    'learning.self_asserted':
      'What you can do is something you record yourself. eigentliCH does not examine it.',
    'learning.no_qualification': 'eigentliCH awards no qualification.',
    'learning.follows': 'Stands alongside',
    'learning.follows_open': 'You have recorded nothing for this yet.',
    'learning.evidences': 'This unit evidences',
    'learning.you_asserted': 'You have recorded that this holds for you.',
    'learning.not_asserted': 'Nothing is recorded for this yet.',
    'learning.leads_to': 'Leads to',
    'learning.body_not_written': 'The material for this unit is not written yet.',
    'learning.fictional': 'An invented unit.',
    'learning.exits_heading': 'Where this leads',
    'learning.exits_lede': 'Three ways out. Only two of them have anything to do with the market place.',
    'learning.exit_touches_market': 'Leads into the market place.',
    'learning.exit_no_market': 'Has nothing to do with the market place.',
    'learning.announced': 'Learning path loaded.',

    // ================================================================================================
    // R-232 — which class each stored category falls into
    // ================================================================================================
    'settings.classes_heading': 'How your material is classified',
    'settings.classes_lede':
      'Every stored category falls into one of four classes. This statement is derived from the data '
      + 'model itself rather than kept by hand.',
    'settings.classes_scheme': 'The four classes',
    'settings.class_k0': 'Published and impersonal: role definitions, assumptions, learning content.',
    'settings.class_k1': 'Identifying, low sensitivity: display name, language, consents.',
    'settings.class_k2': 'Personal and substantive: positions, goals, decisions.',
    'settings.class_k3':
      'Personal and documentary: the documents you deposited and what was read out of them.',
    'settings.classes_top_stays':
      'What falls into {class} is not logged and is not passed to a third party. It goes out only where '
      + 'you cause it to: into your own copy under "Get all your data", which contains the deposited '
      + 'documents including their content, and into the index of your vault that a curator sees for as '
      + 'long as you have given access — never the files themselves.',
    'settings.classes_categories': 'The stored categories',
    'settings.classes_yours': 'Holds material about you.',
    'settings.classes_not_yours': 'Holds nothing about any person.',
    'settings.classes_can_leave': 'May leave the server.',
    'settings.classes_stays': 'Stays on the server, except in your own copy.',
    'settings.classes_field_above': 'Individual fields sit higher',
    'settings.classes_link_tables':
      'Link tables carry no class of their own; they carry the class of the rows they join. So they are '
      + 'not in this list.',
    'settings.classes_derived':
      'This statement is rebuilt from the data model on every request, so it cannot go stale.',
  },
};

export const DEFAULT_LANGUAGE = 'de';

/**
 * Look up a string. Returns the key itself when missing, rather than an empty string or English.
 *
 * A missing German string should look broken in German, not silently become English — that is how a
 * half-translated product ships without anyone noticing which half.
 */
export function t(key, language = DEFAULT_LANGUAGE, values = {}) {
  const table = STRINGS[language] || STRINGS[DEFAULT_LANGUAGE];
  let text = table[key];
  if (text === undefined) return key;
  for (const [name, value] of Object.entries(values)) {
    text = text.split(`{${name}}`).join(String(value));
  }
  return text;
}

export function languages() {
  return Object.keys(STRINGS);
}
