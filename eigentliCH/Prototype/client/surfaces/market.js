// S-11 — the Market Place. The screen behind the door that said "Noch nicht gebaut."
//
// **What was behind that placeholder.** `services/marketplace.py` is the most rigorously guarded module in
// the build: an ordering function whose whole signature is C-08, a role filter that describes how to remove
// itself, a disclosure gate that refuses rather than warns, and two opposite promises about the same
// surface — browsing and contacting are never gated (R-004), being listed as supply always is (R-005). None
// of it was reachable. `#/market` rendered a sentence saying so.
//
// ===========================================================================================================
// C-08: ORDERING CANNOT BE BOUGHT, AND THIS FILE IS WHERE IT WOULD BE SOLD
// ===========================================================================================================
//
// The ordering arrives **decided**. `ordering_key` is handed three integers and an opaque tiebreak and can
// reach nothing else; `_in_order` is the only `sorted` call in the service. So the one thing this file must
// not do is have an opinion about order:
//
//   * **`entries` is iterated in the order it arrives.** There is no `sort`, no `reverse`, no `slice` that
//     promotes anything, and no second list. A client-side sort would move the decision from a guarded
//     function into an unguarded one, which is C-08 defeated without a single line of the service changing.
//   * **Nothing implies paid placement.** No "featured", no "sponsored", no "top supplier", no ribbon, no
//     first-position highlight, no ordinal number beside an entry. A member must not be able to read this
//     screen as an advertising rank, because it is not one — and a screen that looked like one would make
//     the guarantee worthless however true it stayed underneath.
//   * **The three inputs are named on screen**, from the payload's own `ordering_inputs`, together with
//     `ordering_is_not_purchasable`. A74 is why `role_match` is described as a *share* of what an entry
//     declares rather than a count of matches: a count is monotone in how many roles you tick, so ticking
//     all four was free and it dominated the ordering. A share is capped at 1, so no declaration can beat
//     another declaration — the best it can do is tie, and a tie is broken by the two earned inputs.
//   * **No number from the ordering is rendered.** Not the share, not the evidence count, not the presence
//     count. R-221 forbids showing attendance back to a member, and a rendered share would be a standing
//     figure beside a supplier — C-07 in the one place a "relevance" figure looks harmless.
//
// **R-202: every listing displays its disclosures.** Displayed, not "on request" — so they are text on the
// card, not a toggle a member has to find. `publish` is what makes them always present, so a published
// listing arriving with none is a broken promise rather than an empty field, and this file says so on the
// card instead of rendering nothing. `none_declared` is a disclosure and reads as one: R-202's whole point
// is that "we declare nothing" is a positive statement.
//
// **R-201: the filter is visible and removable, and the payload says how.** `filter.remove_by` carries the
// parameter and the value that drops it, so this client sends the name the payload prints back rather than
// a literal of its own. The filter travels in the hash — see `main.js::hashQuery` for the reasoning it
// shares with S-07: a filter held in a variable survives a route change invisibly.
//
// **R-205: a member offer is a peer.** One list, one ordering function, one card treatment. Not provider
// listings with member offers underneath them, and not a separate section, which is the "beneath" R-205
// forbids drawn in layout instead of in code.
//
// **R-200: indexed by role, not by profession.** The four roles are the filter. `GET
// /api/marketplace/roles` is deliberately not called: its own docstring says it is built by asking `browse`
// once per role, so rendering it beside a filtered browse would be the same entries on the screen twice.
// The role *names* come from the member's own role grid rather than from this client's string table,
// because a role's name is a content record the server owns (A19, A21) and a second copy in `i18n.js` is
// the A73 shape.
//
// **NG-04: eigentliCH awards no qualification and verifies nothing.** `qualification_claim` is null in every
// payload here and the screen states it. `registration_refs_are_the_providers_own` is rendered as the
// sentence it is, beside the references themselves.
//
// **C-01:** nothing here recommends a supplier, compares two of them for the member, or says which is
// suitable. The cards state what each entry says about itself.

import { announce, button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import {
  applyToBeListed,
  declareDisclosure,
  detailText,
  getListing,
  getListingContact,
  getListings,
  getOfferContact,
  getRoleGrid,
  publishApplication,
} from '../app/api.js';

//: R-202. Always offerable on an application, whatever the market place happens to carry today: "nothing
//: to declare" is the one disclosure that cannot be read off other people's listings, and a form that
//: could not express it would force an applicant to invent a relationship or abandon the application.
const NONE_DECLARED = 'none_declared';

/**
 * A key rendered as a word, or as itself.
 *
 * Used for domains, pipelines, offer kinds, offer directions and disclosure kinds — all of them server
 * enumerations whose *words* belong in the client's string table. `services/community.py` states the same
 * division for gathering kinds: "the key, not a word. The words live in the client's string table."
 *
 * **Falling back to the key is the point.** A vocabulary the server grows and this table does not must
 * appear on screen as something unlabelled, never as nothing — a silently dropped domain is a listing a
 * member cannot see the shape of.
 */
function word(prefix, key, language) {
  if (!key) return null;
  const full = `market.${prefix}_${key}`;
  const value = t(full, language);
  return value === full ? key : value;
}

/**
 * `{roleKey: name}` from the member's own role grid.
 *
 * **Why the grid and not a list here.** The four role names are content records with a published
 * definition and a reviewed German wording (A21, A42); this client does not own them. The grid payload is
 * where it already reads them, and `grid.js` labels a role *row* the same way — with the display name of
 * that role's first cell — so the market place's filter uses the same words as the member's own plan. That
 * is what makes R-201's pre-filter legible: "filtered by the roles in your plan" is only true if the words
 * match.
 */
function roleNames(grid) {
  const names = {};
  for (const cell of (grid && grid.cells) || []) {
    if (!(cell.role in names)) names[cell.role] = cell.display;
  }
  return names;
}

function roleLabel(key, names) {
  return names[key] || key;
}

/** `31.08.2026` from an ISO timestamp. A disclosure is dated to the day. */
function readableDate(iso, language) {
  if (typeof iso !== 'string') return '';
  const parts = iso.split('T')[0].split('-');
  if (parts.length !== 3) return iso;
  return language === 'de' ? `${parts[2]}.${parts[1]}.${parts[0]}` : parts.join('-');
}

// ---------------------------------------------------------------- R-201, the visible removable filter

/**
 * The filter, as a statement plus controls.
 *
 * Every branch here is a field of `payload.filter` rather than something reconstructed from what this
 * client asked for: `applied`, `source`, `reason` and `remove_by`. The service's own docstring says the
 * block exists so that "the filter is visible and removable" is a promise about the payload rather than
 * about a button somebody remembers to build, and reading it back is what takes that at its word.
 */
function filterSection(filter, names, { language, onFilter }) {
  const block = filter || {};
  const chosen = new Set(block.roles || []);
  const all = block.all_roles || [];

  // Which of the three ways in happened, named. A member who is seeing a subset of the market place has to
  // be able to tell that they are, and why.
  let statement = t('market.filter_none', language);
  if (block.applied && block.source === 'member_role_grid') statement = t('market.filter_from_grid', language);
  else if (block.applied) statement = t('market.filter_chosen', language);
  else if (block.reason === 'role_grid_is_empty') statement = t('market.filter_grid_empty', language);
  else if (block.source === 'removed_by_the_member') statement = t('market.filter_removed', language);

  // One button per role, `aria-pressed` for the ones in force. A toggle rather than a link, because
  // pressing it changes what the list contains rather than where the member is.
  const toggles = all.map((role) => button(roleLabel(role, names), {
    class: 'add',
    'aria-pressed': String(chosen.has(role)),
    onClick: () => {
      const next = new Set(chosen);
      if (next.has(role)) next.delete(role);
      else next.add(role);
      // Emptying the selection is not the same act as removing the filter, and the payload distinguishes
      // them: `removed_by_the_member` against `role_grid_is_empty`. An empty explicit selection would be
      // an explicit list of nothing, which the service reads as "pre-filter from the grid" — the opposite
      // of what a member unticking their last role meant. So it is sent as the removal.
      onFilter(next.size ? [...all].filter((key) => next.has(key)) : [block.remove_by && block.remove_by.value].filter(Boolean));
    },
  }));

  const nodes = [
    h('span', { class: 'lbl', text: t('market.filter_heading', language) }),
    h('p', { class: 'field-hint', text: statement }),
    h('div', { class: 'actions' }, toggles),
  ];

  // The removal control, named by the payload. Offered only where there is something to remove — a
  // "remove filter" button beside an unfiltered list is a control that does nothing, which is worse than
  // no control at all.
  if (block.applied && block.remove_by && block.remove_by.value) {
    nodes.push(h('div', { class: 'actions' }, [
      button(t('market.filter_remove', language), {
        class: 'add',
        onClick: () => onFilter([block.remove_by.value]),
      }),
    ]));
  }

  return h('section', { class: 'market-filter' }, nodes);
}

// ---------------------------------------------------------------- C-08, said on the screen

/**
 * What decides the order, from the payload's own list, and that it is not for sale.
 *
 * **The three inputs are named and none of them is given a figure.** Naming them is what lets a member
 * read the list as something other than an advertising rank; printing the numbers would put a standing
 * score beside every supplier, which is the C-07 shape this whole product exists without.
 */
function orderingSection(payload, language) {
  const inputs = payload.ordering_inputs || [];
  return h('section', { class: 'market-ordering' }, [
    h('span', { class: 'lbl', text: t('market.ordering_heading', language) }),
    // Only where the payload says so. The claim on screen is the server's claim, not this file's.
    payload.ordering_is_not_purchasable
      ? h('p', { class: 'field-hint', text: t('market.ordering_not_for_sale', language) })
      : null,
    inputs.length
      ? h('ul', {}, inputs.map((name) => h('li', {
          text: word('ordering_input', name, language) || name,
        })))
      : null,
    // A74, in one sentence: what a supplier declares about itself has a ceiling, so breadth is not free.
    inputs.includes('role_match')
      ? h('p', { class: 'field-hint', text: t('market.ordering_share', language) })
      : null,
    payload.qualification_claim === null
      ? h('p', { class: 'field-hint', text: t('market.no_qualification', language) })
      : null,
  ]);
}

// ---------------------------------------------------------------- R-202, the disclosures

/**
 * R-202. Every listing's disclosures, as text on the card.
 *
 * **Not a toggle.** "Displays its disclosures" and "offers to show its disclosures" are different
 * promises, and only one of them is the requirement. A `<details>` element here would be the most natural
 * way to keep the card short and it is the one shape this cannot take.
 *
 * **An empty list is rendered as the broken promise it would be.** `publish` refuses a listing with no
 * disclosure, so a published listing carrying none cannot happen through the product — and if it ever
 * does, a member reading a card with a silent gap where the disclosures go learns nothing. The sentence
 * says the listing states none, which is a fact about the listing rather than about this screen.
 */
function disclosuresNode(entries, language) {
  const rows = entries || [];
  return h('div', { class: 'field disclosures' }, [
    h('span', { class: 'field-label', text: t('market.disclosures_heading', language) }),
    rows.length
      ? h('div', {}, rows.map((row) => h('div', { class: 'disclosure' }, [
          h('p', { class: 'field-label', text: word('disclosure', row.kind, language) || row.kind }),
          h('p', { class: 'cell-prompt', text: row.statement }),
          h('p', {
            class: 'position-meta',
            text: `${t('market.disclosure_declared_by', language)}: ${row.declared_by} `
              + `(${readableDate(row.declared_at, language)})`,
          }),
        ])))
      : h('p', { class: 'notice', text: t('market.disclosures_absent', language) }),
  ]);
}

// ---------------------------------------------------------------- the two kinds of entry (R-205)

/**
 * A contact region that fills itself in when asked, for the one kind of entry whose contact is not in the
 * browse payload.
 *
 * R-004 twice over: the request is made without any capability being read, and the payload's own
 * `gated_on: null` is rendered as the sentence it is. A member offer carries no address by design — it is
 * reached through the member — so what comes back is a reference, and the screen says that rather than
 * printing a bare identifier and hoping.
 */
function offerContactNode(entry, language) {
  const region = h('div', { class: 'field' });
  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });

  const ask = button(t('market.contact_offer', language), {
    class: 'add',
    onClick: async (event) => {
      const pressed = event.currentTarget;
      pressed.disabled = true;
      error.setAttribute('hidden', '');
      try {
        const contact = await getOfferContact(entry.id);
        clear(region);
        region.append(
          h('span', { class: 'field-label', text: t('market.contact_heading', language) }),
          h('p', { class: 'field-hint', text: t('market.contact_via_member', language) }),
          contact.contact_via && contact.contact_via.value
            ? h('p', { class: 'position-label', text: String(contact.contact_via.value) })
            : null,
          contact.gated_on === null
            ? h('p', { class: 'field-hint', text: t('market.contact_not_gated', language) })
            : null,
        );
      } catch (failure) {
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        pressed.disabled = false;
      }
    },
  });

  return h('div', {}, [region, error, h('div', { class: 'actions' }, [ask])]);
}

/** Shared head of both card kinds: which kind it is, said in words rather than by placement or colour. */
function entryKindNode(entry, language) {
  return h('p', {
    class: 'cell-capital',
    text: entry.entry_kind === 'member_offer'
      ? t('market.kind_member_offer', language)
      : t('market.kind_provider_listing', language),
  });
}

/**
 * One provider listing.
 *
 * The contact is printed here rather than fetched, because it is already in the browse payload and R-004's
 * promise is strongest when nothing has to be asked for. `GET /listings/{id}/contact` is used on the detail
 * screen, where it adds the one thing this card cannot say for itself: that there is no gate.
 */
function listingNode(entry, names, { language, onOpen }) {
  const supplier = entry.supplier || {};
  return h('div', { class: 'cell listing', 'data-entry-kind': entry.entry_kind }, [
    entryKindNode(entry, language),
    h('p', { class: 'position-label', text: entry.title }),
    entry.summary ? h('p', { class: 'cell-prompt', text: entry.summary }) : null,

    // R-200. The roles this listing declares, in the member's own words for them.
    (entry.roles || []).length
      ? h('p', {
          class: 'position-meta',
          text: `${t('market.roles_label', language)}: `
            + entry.roles.map((role) => roleLabel(role, names)).join(', '),
        })
      : null,
    entry.domain
      ? h('p', {
          class: 'position-meta',
          text: `${t('market.domain_label', language)}: ${word('domain', entry.domain, language)}`,
        })
      : null,
    // R-204. Which pipeline this listing declared — the listing's own statement, not a finding.
    entry.qualification_pipeline
      ? h('p', {
          class: 'position-meta',
          text: `${t('market.pipeline_label', language)}: `
            + word('pipeline', entry.qualification_pipeline, language),
        })
      : null,

    // NG-04. The references belong to the provider who supplied them, and the payload says so in a field
    // of its own; rendering the sentence beside them is what stops them reading as eigentliCH's verification.
    (entry.registration_refs || []).length
      ? h('div', { class: 'field' }, [
          h('span', { class: 'field-label', text: t('market.registration_refs_label', language) }),
          h('ul', {}, entry.registration_refs.map((ref) => h('li', { text: ref }))),
          entry.registration_refs_are_the_providers_own
            ? h('span', { class: 'field-hint', text: t('market.registration_refs_own', language) })
            : null,
        ])
      : null,

    supplier.display_name
      ? h('p', {
          class: 'position-meta',
          text: `${t('market.supplier_label', language)}: ${supplier.display_name}`,
        })
      : null,
    supplier.contact
      ? h('p', {
          class: 'position-meta',
          text: `${t('market.contact_heading', language)}: ${supplier.contact}`,
        })
      : null,

    // R-202, on every card without exception.
    disclosuresNode(entry.disclosures, language),

    // A41. The seed content is fictional and carries the marker; it survives into what is rendered rather
    // than being a fact only the database knows.
    entry.fictional ? h('p', { class: 'field-hint', text: t('market.fictional', language) }) : null,

    h('div', { class: 'actions' }, [
      button(t('market.open_listing', language), { class: 'add', onClick: () => onOpen(entry.id) }),
    ]),
  ]);
}

/**
 * One member offer, as a peer of a provider listing (R-205).
 *
 * Same card, same class, same place in the same list. It carries no standing numbers — `_entry_for_offer`
 * does not compose any, and R-221's reason is that a member offer is a member looking at their own row as
 * often as anyone else's.
 */
function offerNode(entry, names, { language }) {
  return h('div', { class: 'cell listing', 'data-entry-kind': entry.entry_kind }, [
    entryKindNode(entry, language),
    h('p', { class: 'position-label', text: entry.title }),
    entry.body ? h('p', { class: 'cell-prompt', text: entry.body }) : null,
    h('p', {
      class: 'position-meta',
      text: [word('offer_kind', entry.kind, language), word('direction', entry.direction, language)]
        .filter(Boolean).join(' — '),
    }),
    (entry.roles || []).length
      ? h('p', {
          class: 'position-meta',
          text: `${t('market.roles_label', language)}: `
            + entry.roles.map((role) => roleLabel(role, names)).join(', '),
        })
      : null,
    entry.fictional ? h('p', { class: 'field-hint', text: t('market.fictional', language) }) : null,
    offerContactNode(entry, language),
  ]);
}

function entryNode(entry, names, { language, onOpen }) {
  return entry.entry_kind === 'member_offer'
    ? offerNode(entry, names, { language })
    : listingNode(entry, names, { language, onOpen });
}

// ---------------------------------------------------------------- R-005, applying to be listed

/**
 * Which pipeline each domain goes through, read off the listings the market place is already serving.
 *
 * **Why this is derived rather than written down.** R-204 makes the pipeline a *declaration* and the server
 * refuses a listing whose declaration does not match its domain — so a client that wrote the mapping out
 * would be holding a second copy of a server rule, which is the A73 shape and the one this build has paid
 * for three times. Reading it off published listings cannot contradict the server, because it is the
 * server's own data.
 *
 * The cost is stated rather than hidden: a domain with no published listing yet cannot be offered, and the
 * form says which domains it is offering rather than implying they are all of them.
 */
function pipelinesByDomain(entries) {
  const map = {};
  for (const entry of entries || []) {
    if (entry.entry_kind !== 'provider_listing') continue;
    if (entry.domain && entry.qualification_pipeline && !(entry.domain in map)) {
      map[entry.domain] = entry.qualification_pipeline;
    }
  }
  return map;
}

/** R-202. The disclosure kinds the market place actually uses, plus the one that must always be offerable. */
function disclosureKinds(entries) {
  const kinds = new Set([NONE_DECLARED]);
  for (const entry of entries || []) {
    for (const row of entry.disclosures || []) if (row.kind) kinds.add(row.kind);
  }
  return [...kinds];
}

/**
 * The draft an application returns, and the two steps that get it into the market place.
 *
 * **This is rendered in place rather than on a route of its own, and the screen says why.** There is no
 * route that lists a member's own draft listings, so a draft is reachable from the response that created
 * it and from nowhere else: a reload loses the address. That is a real limitation of the surface and the
 * member is told it here, at the moment it starts to matter, rather than discovering it afterwards.
 */
function draftNode(listing, { language, declaredBy, kinds }) {
  const state = h('div', { class: 'field' });
  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });

  const kindSelect = h('select', { name: 'disclosure_kind', required: '' }, [
    h('option', { value: '', text: t('market.disclosure_kind_choose', language) }),
    ...kinds.map((kind) => h('option', {
      value: kind,
      text: word('disclosure', kind, language) || kind,
    })),
  ]);
  const statement = h('textarea', { name: 'disclosure_statement', rows: '3', required: '' });

  const publish = button(t('market.publish', language), {
    class: 'primary',
    onClick: async (event) => {
      const pressed = event.currentTarget;
      pressed.disabled = true;
      error.setAttribute('hidden', '');
      try {
        const published = await publishApplication(listing.id);
        clear(state);
        state.append(h('p', {
          class: 'field-label',
          text: `${t('market.status_label', language)}: `
            + (word('status', published.status, language) || published.status),
        }));
        announce(t('market.published_announced', language));
      } catch (failure) {
        // The 422 for a listing with no disclosure is R-202 working. Shown as what happened, because a
        // member who reads it as a fault will look for a way around it.
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
        pressed.disabled = false;
      }
    },
  });

  const add = button(t('market.disclosure_add', language), {
    class: 'add',
    onClick: async (event) => {
      const pressed = event.currentTarget;
      error.setAttribute('hidden', '');
      if (!kindSelect.value || !statement.value.trim()) {
        error.textContent = t('market.disclosure_missing_fields', language);
        error.removeAttribute('hidden');
        return;
      }
      pressed.disabled = true;
      try {
        await declareDisclosure(listing.id, {
          kind: kindSelect.value,
          statement: statement.value.trim(),
          declaredBy,
        });
        statement.value = '';
        clear(state);
        state.append(h('p', { class: 'field-hint', text: t('market.disclosure_recorded', language) }));
        announce(t('market.disclosure_recorded', language));
      } catch (failure) {
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
      } finally {
        pressed.disabled = false;
      }
    },
  });

  return h('div', { class: 'cell draft' }, [
    h('h3', { text: t('market.draft_heading', language) }),
    h('p', { class: 'field-hint', text: t('market.draft_not_listed', language) }),
    h('p', { class: 'field-hint', text: t('market.draft_only_here', language) }),
    h('p', {
      class: 'position-meta',
      text: `${t('market.status_label', language)}: `
        + (word('status', listing.status, language) || listing.status),
    }),
    // R-202's gate, quoted from the payload's own two fields rather than described.
    listing.publishable === false
      ? h('p', { class: 'field-hint', text: t('market.draft_needs_disclosure', language) })
      : null,

    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.disclosure_kind', language) }),
      kindSelect,
      h('span', { class: 'field-hint', text: t('market.disclosure_kind_hint', language) }),
    ]),
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.disclosure_statement', language) }),
      statement,
    ]),
    state,
    error,
    h('div', { class: 'actions' }, [add, publish]),
  ]);
}

/**
 * R-005. The application to be listed as supply — **the one gated act on this surface.**
 *
 * **The gate is the server's and this form does not second-guess it.** There is no check here for whether
 * the member holds a capability assertion: the 403 comes back with the reason written out, and a client
 * that pre-empted it would be a second copy of R-005's rule, drifting. What the form does instead is say
 * which evidence the chosen domain's pipeline reads, so a refusal is legible rather than surprising.
 *
 * **R-204's asymmetry is built into the shape of the form.** A capability listing may carry no registration
 * reference — the service refuses one rather than dropping it — so the reference field is *absent* when the
 * chosen domain's pipeline is the capability one, and present when it is the professional one. Two pipelines
 * that are not interchangeable, made visible as two different questions.
 */
function applySection(vocabulary, { language, onApplied }) {
  const pipelines = pipelinesByDomain(vocabulary.entries);
  const kinds = disclosureKinds(vocabulary.entries);
  const names = vocabulary.names;
  const roles = (vocabulary.filter && vocabulary.filter.all_roles) || [];

  const displayName = h('input', { type: 'text', name: 'display_name', maxlength: '200', required: '' });
  const title = h('input', { type: 'text', name: 'title', maxlength: '200', required: '' });
  const summary = h('textarea', { name: 'summary', rows: '3' });
  const contact = h('input', { type: 'text', name: 'contact', maxlength: '200' });

  // Nothing preselected — A86's fourth defect, and here the inference would be eigentliCH choosing which
  // part of the market a member is offering themselves into.
  const domainSelect = h('select', { name: 'domain', required: '' }, [
    h('option', { value: '', text: t('market.apply_domain_choose', language) }),
    ...Object.keys(pipelines).map((domain) => h('option', {
      value: domain,
      text: word('domain', domain, language),
    })),
  ]);

  const roleBoxes = roles.map((role) => {
    const box = h('input', { type: 'checkbox', class: 'consent-box', value: role });
    return {
      role,
      box,
      node: h('label', { class: 'field consent-agree' }, [
        box,
        h('span', { class: 'field-label', text: roleLabel(role, names) }),
      ]),
    };
  });

  const refs = h('input', { type: 'text', name: 'registration_refs', maxlength: '400' });
  const refsField = h('label', { class: 'field', hidden: '' }, [
    h('span', { class: 'field-label', text: t('market.apply_refs', language) }),
    refs,
    h('span', { class: 'field-hint', text: t('market.apply_refs_hint', language) }),
  ]);
  const pipelineNote = h('p', { class: 'field-hint' });

  /** R-204, as the form's own shape: which evidence this domain's pipeline reads, and which field goes with it. */
  function followDomain() {
    const pipeline = pipelines[domainSelect.value];
    if (!pipeline) {
      pipelineNote.textContent = '';
      refsField.setAttribute('hidden', '');
      return;
    }
    pipelineNote.textContent = `${t('market.pipeline_label', language)}: `
      + `${word('pipeline', pipeline, language)} — `
      + t(pipeline === 'capability' ? 'market.apply_gate_capability' : 'market.apply_gate_registration',
        language);
    if (pipeline === 'capability') refsField.setAttribute('hidden', '');
    else refsField.removeAttribute('hidden');
  }
  domainSelect.addEventListener('change', followDomain);

  const error = h('div', { class: 'notice error', role: 'alert', hidden: '' });
  const draftRegion = h('div', {});
  const submit = h('button', { type: 'submit', class: 'primary' }, [t('market.apply_submit', language)]);

  const form = h('form', {
    class: 'position-form',
    hidden: '',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');
      const chosenRoles = roleBoxes.filter((entry) => entry.box.checked).map((entry) => entry.role);
      if (!domainSelect.value) {
        error.textContent = t('market.apply_no_domain', language);
        error.removeAttribute('hidden');
        domainSelect.focus();
        return;
      }
      if (!chosenRoles.length) {
        error.textContent = t('market.apply_no_role', language);
        error.removeAttribute('hidden');
        return;
      }

      const pipeline = pipelines[domainSelect.value];
      const payload = {
        display_name: displayName.value.trim(),
        title: title.value.trim(),
        domain: domainSelect.value,
        qualification_pipeline: pipeline,
        roles: chosenRoles,
      };
      if (summary.value.trim()) payload.summary = summary.value.trim();
      if (contact.value.trim()) payload.contact = contact.value.trim();
      // R-204 again: references travel only on the pipeline that reads them. Sending them on a capability
      // listing is refused by the service rather than ignored, and this form does not put the member in
      // front of that refusal.
      if (pipeline !== 'capability' && refs.value.trim()) {
        payload.registration_refs = refs.value.split(',').map((ref) => ref.trim()).filter(Boolean);
      }

      submit.disabled = true;
      try {
        const listing = await applyToBeListed(payload);
        clear(draftRegion);
        draftRegion.append(draftNode(listing, {
          language,
          declaredBy: payload.display_name,
          kinds,
        }));
        // Announced after the draft is on screen, so the outcome is not overwritten by anything the
        // rendering behind it says. The same ordering the grant screen and the capability form use.
        announce(t('market.applied_announced', language));
        if (onApplied) onApplied();
      } catch (failure) {
        error.textContent = detailText(failure);
        error.removeAttribute('hidden');
      } finally {
        submit.disabled = false;
      }
    },
  }, [
    h('h3', { text: t('market.apply_heading', language) }),
    h('p', { class: 'field-hint', text: t('market.apply_lede', language) }),
    // R-004 and R-005 are opposite promises about one surface, so both are named where the gated one is.
    h('p', { class: 'field-hint', text: t('market.apply_only_gate', language) }),

    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.apply_display_name', language) }),
      displayName,
    ]),
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.apply_title', language) }),
      title,
    ]),
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.apply_summary', language) }),
      summary,
    ]),
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.apply_contact', language) }),
      contact,
    ]),
    h('label', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.apply_domain', language) }),
      domainSelect,
      h('span', { class: 'field-hint', text: t('market.apply_domain_hint', language) }),
    ]),
    pipelineNote,
    h('div', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.apply_roles', language) }),
      h('span', { class: 'field-hint', text: t('market.apply_roles_hint', language) }),
      ...roleBoxes.map((entry) => entry.node),
    ]),
    refsField,
    error,
    h('div', { class: 'actions' }, [submit]),
    draftRegion,
  ]);

  const opener = button(t('market.apply_open', language), {
    class: 'add',
    'aria-expanded': 'false',
    onClick: (event) => {
      const opening = form.hasAttribute('hidden');
      if (opening) form.removeAttribute('hidden');
      else form.setAttribute('hidden', '');
      event.currentTarget.setAttribute('aria-expanded', String(opening));
    },
  });

  return h('section', { class: 'market-apply' }, [opener, form]);
}

// ---------------------------------------------------------------- loading

/**
 * A11: no member id anywhere. The browsing member, the asking member and the applying member are the
 * token's.
 *
 * **Two browses where the filter is applied, and the second one is not laziness avoided.** The application
 * form offers the domains the market place carries, read off published listings (see
 * `pipelinesByDomain`); reading them off a *role-filtered* browse would let the filter narrow what a member
 * is allowed to apply under, which is a filter deciding something it has no business deciding. So the
 * vocabulary comes from an unfiltered browse. Where the filter is already removed the one payload serves
 * both and there is no second request.
 */
export async function load(language, { roles = null, domain = null } = {}) {
  const [listings, grid] = await Promise.all([
    getListings({ roles, domain, language }),
    getRoleGrid(language),
  ]);
  const unfiltered = listings.filter && listings.filter.applied
    ? await getListings({ roles: [listings.filter.remove_by.value], language })
    : listings;
  return { listings, grid, unfiltered };
}

/** One listing, and the contact route that states in a field of its own that nothing gates it. */
export async function loadOne(listingId, language) {
  const [detail, contact] = await Promise.all([
    getListing(listingId, language),
    // A 404 here would mean the listing is not published, which the detail call already answers; letting
    // this one fail on its own would replace a legible refusal with an unexplained one.
    getListingContact(listingId).catch(() => null),
  ]);
  const grid = await getRoleGrid(language);
  return { detail, contact, grid };
}

export function render(container, payload, { language, onFilter, onOpen }) {
  clear(container);
  const listings = payload.listings || {};
  const names = roleNames(payload.grid);

  container.append(
    h('span', { class: 'lbl', text: t('market.eyebrow', language) }),
    h('h1', { text: t('market.title', language) }),
    h('p', { class: 'lede', text: t('market.lede', language) }),
    // R-004, stated where a member arrives rather than only where they act: reading and getting in touch
    // are not gated on anything, and the payload says both.
    listings.browsing_is_not_gated && listings.contacting_is_not_gated
      ? h('p', { class: 'field-hint', text: t('market.not_gated', language) })
      : null,
    // A41. Whole-surface marker, because the seed suppliers are invented people.
    listings.fictional ? h('p', { class: 'field-hint', text: t('market.fictional_all', language) }) : null,
  );

  container.append(filterSection(listings.filter, names, { language, onFilter }));
  container.append(orderingSection(listings, language));

  // R-205. One list of peers, in the order it arrived. No sort, no grouping by kind, no slice.
  const entries = listings.entries || [];
  container.append(
    entries.length
      ? h('div', { class: 'grid market-entries' },
        entries.map((entry) => entryNode(entry, names, { language, onOpen })))
      // R-110's shape applied to a filtered list: what is here, and what would be. Not a suggestion to
      // change the filter — that is the member's own decision and the controls are above.
      : h('p', { class: 'field-hint', text: t('market.no_entries', language) }),
  );

  container.append(applySection({
    entries: (payload.unfiltered || listings).entries,
    filter: listings.filter,
    names,
  }, { language }));

  announce(t('market.announced', language));
}

export function renderOne(container, payload, { language, onBack }) {
  clear(container);
  const detail = payload.detail || {};
  const entry = detail.listing || {};
  const names = roleNames(payload.grid);

  container.append(
    h('span', { class: 'lbl', text: t('market.eyebrow', language) }),
    h('h1', { text: entry.title || t('market.title', language) }),
    h('div', { class: 'actions' }, [
      button(t('market.back', language), { class: 'add', onClick: onBack }),
    ]),
  );

  container.append(h('div', { class: 'grid' }, [listingNode(entry, names, {
    language,
    // On the detail screen the card's own control would lead back to the card. It is given a handler that
    // returns to the list, so there is no button on this page that does nothing.
    onOpen: () => onBack(),
  })]));

  // The contact route's own contribution: `gated_on: null`, said as a sentence. The address itself is
  // already on the card — R-004 is not "available on request".
  if (payload.contact) {
    container.append(h('section', { class: 'field' }, [
      h('span', { class: 'field-label', text: t('market.contact_heading', language) }),
      payload.contact.contact
        ? h('p', { class: 'position-label', text: payload.contact.contact })
        : null,
      payload.contact.gated_on === null
        ? h('p', { class: 'field-hint', text: t('market.contact_not_gated', language) })
        : null,
    ]));
  }

  container.append(orderingSection(detail, language));
  announce(t('market.announced_one', language));
}
