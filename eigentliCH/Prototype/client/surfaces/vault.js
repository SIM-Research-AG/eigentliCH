// S-06 — the Vault. What the member owns, kept where nothing overwrites it.
//
// **R-153 is a layout decision, not a sentence in the copy.** A member-authored note is a vault item of
// equal standing to a document, so there is one list and one form. A note is not a second section, not a
// lesser kind and not a "quick note" box beside the real thing: it is the same form with no file attached,
// and the file field says so where a member is looking when they decide.
//
// **R-150: four intake paths behind one interface, and two of them are not built.** The unbuilt ones are
// rendered as unavailable options rather than hidden. Hiding them would make the interface look finished
// and leave a member wondering why a forwarding address was promised; showing them disabled says what the
// product is and what it is not. The payload names which is which — this file does not hardcode the list.
//
// **R-151: provenance is shown, and a disagreement shows both values.** A value the member typed outranks
// one that was read out of a file, permanently. Where they disagree the extracted value is shown too,
// underneath, labelled — because a disagreement between a person and a reader is two facts, not one
// correction, and the member is the one who can tell which is right.
//
// **R-041 / R-152:** version and what it supersedes are on the card, and an expiry date is not a detail in
// a fold — it is the field that becomes a prepared decision in The Know.
//
// **R-154: the export asks nobody.** One button, no approval step, no curator in the path. The endpoint
// returns the whole thing as JSON and this hands it to the browser as a file.
//
// R-113: no counts, no meters, no "n items of m". A list is a list.

import { button, clear, h } from '../app/dom.js';
import { t } from '../app/i18n.js';
import { getVault, createVaultItem, requestExport, detailText } from '../app/api.js';

//: `VaultItem.kind` is an enum on the model, so this is the model's list rather than an invention. Order is
//: the model's order; notes, arrangements and learning sit among the documents rather than below them.
const KINDS = ['policy', 'statement', 'contract', 'note', 'arrangement', 'learning', 'other'];

function field(labelText, control, hint) {
  return h('label', { class: 'field' }, [
    h('span', { class: 'field-label', text: labelText }),
    control,
    hint ? h('span', { class: 'field-hint', text: hint }) : null,
  ]);
}

/** Strip the `data:...;base64,` prefix the FileReader adds. The API wants the payload, not the URL. */
function readAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error('the file could not be read'));
    reader.onload = () => {
      const result = String(reader.result);
      const comma = result.indexOf(',');
      resolve(comma >= 0 ? result.slice(comma + 1) : result);
    };
    reader.readAsDataURL(file);
  });
}

/**
 * R-151. One extracted or member-stated field, with where the value came from.
 *
 * `provenance: "member"` is rendered first and without qualification. Anything else is rendered as a
 * reading, with its confidence where one was recorded — a confidence that is absent renders as absent
 * rather than as certainty.
 */
function extractedFieldNode(name, record, language) {
  const fromMember = record.provenance === 'member';
  const disagreement = record.disagrees_with_extraction;

  return h('div', { class: 'position' }, [
    h('div', { class: 'position-label', text: name }),
    h('div', { class: 'position-magnitude', text: String(record.value) }),
    h('div', {
      class: 'position-meta',
      text: fromMember
        ? t('vault.provenance_member', language)
        : t('vault.provenance_extraction', language),
    }),
    record.confidence !== null && record.confidence !== undefined
      ? h('div', {
          class: 'position-meta',
          text: `${t('vault.confidence', language)}: ${record.confidence}`,
        })
      : null,
    // Both values, never one. The member's stands above; the reading is shown so it cannot be quietly
    // dropped, and so the member can see what the file appears to say.
    disagreement
      ? h('div', { class: 'notice' }, [
          h('p', { text: t('vault.disagreement', language), style: 'margin:0' }),
          h('p', {
            class: 'lbl',
            text: `${t('vault.provenance_extraction', language)}: ${disagreement.value}`,
            style: 'margin:8px 0 0',
          }),
        ])
      : null,
  ]);
}

function itemNode(item, language) {
  const fields = Object.entries(item.extracted_fields || {});

  return h('div', { class: 'role-row', style: 'grid-template-columns:1fr' }, [
    h('div', { class: 'cell', style: 'border-left-width:0' }, [
      h('span', { class: 'cell-capital', text: t(`vault.kind_${item.kind}`, language) }),
      h('div', { class: 'position-label', text: item.title }),

      // R-041. The version and what it replaced, on the card rather than in a history nobody opens.
      h('div', {
        class: 'position-meta',
        text: `${t('vault.version', language)} ${item.version}`
          + (item.supersedes_id ? ` · ${t('vault.supersedes', language)}` : ''),
      }),

      // R-152. An expiry date is first-class here because it is first-class in the data: it is what
      // produces the prepared decisions listed in The Know.
      h('div', {
        class: 'position-meta',
        text: item.expiry_date
          ? `${t('vault.expiry', language)}: ${item.expiry_date}`
          : t('vault.no_expiry', language),
      }),

      // R-153 again, at the item: a note says it has no file, and says it as a fact rather than as a lack.
      h('div', {
        class: 'position-meta',
        text: `${t(`vault.source_${item.source}`, language)} · `
          + (item.has_content ? t('vault.has_content', language) : t('vault.note_only', language)),
      }),

      item.notes ? h('p', { class: 'cell-prompt', text: item.notes }) : null,

      fields.length
        ? h('div', { class: 'field' }, [
            h('span', { class: 'lbl', text: t('vault.fields', language) }),
            ...fields.map(([name, record]) => extractedFieldNode(name, record, language)),
          ])
        : null,
    ]),
  ]);
}

// ---------------------------------------------------------------- the export (R-154)

function exportSection(memberId, language) {
  const region = h('div', { class: 'field' });

  const trigger = button(t('vault.export', language), {
    class: 'add',
    onClick: async (event) => {
      const control = event.currentTarget;
      control.disabled = true;
      clear(region);
      try {
        // **A POST now, and it was a GET.** That was the outstanding half of A93: `GET /api/export` is
        // R-154's plain read and writes **no** Decision, so R-231's "both producing a Decision record"
        // held only on the path nobody called and the member's own record of having asked for their data
        // was never written. A GET must be safe — a prefetch, a retry after a dropped connection, a proxy
        // revalidation or a double-click each repeat one, and each repetition would append to a table
        // R-040 makes append-only, so S-07 would fill with export requests the member never made and
        // there would be no removing them. The document is identical; the request is the POST.
        const payload = await requestExport();
        // Handed to the browser as a file the member keeps. No mail step, no share link, no third party —
        // C-05 means the bytes never leave this machine on their way to their owner.
        const blob = new Blob([JSON.stringify(payload.export, null, 2)], { type: 'application/json' });
        const href = URL.createObjectURL(blob);
        const link = h('a', {
          href,
          download: `eigentlich-export-${memberId}.json`,
          class: 'add',
          style: 'text-decoration:none',
          text: `eigentlich-export-${memberId}.json`,
        });
        region.append(
          h('p', { class: 'field-hint', text: t('vault.export_ready', language) }),
          link,
          // R-231's record, named where it was made. The member can go and read it on S-07.
          h('p', {
            class: 'report-meta',
            text: `${t('settings.export_decision', language)}: ${payload.decision_id}`,
          }),
        );
        // Offered as a click and taken as one: the link stays visible, so a browser that blocks the
        // programmatic download leaves the member something to press rather than nothing.
        link.click();
      } catch (error) {
        region.append(
          h('div', { class: 'notice error', role: 'alert' }, [
            h('p', { text: detailText(error), style: 'margin:0' }),
          ]),
        );
      } finally {
        control.disabled = false;
      }
    },
  });

  return h('div', { class: 'known' }, [
    h('span', { class: 'lbl', text: t('vault.export_label', language) }),
    h('p', { class: 'field-hint', text: t('vault.export_hint', language) }),
    trigger,
    region,
  ]);
}

// ---------------------------------------------------------------- adding an item (R-150, R-153)

function addForm({ language, intake, items, onSaved }) {
  const title = h('input', { type: 'text', name: 'title', required: '', maxlength: '300' });

  const kind = h('select', { name: 'kind' },
    KINDS.map((k) => h('option', { value: k, text: t(`vault.kind_${k}`, language) })));

  // R-150. Every path is listed. The two D-04 has not decided are options a member can see and cannot
  // choose, with the reason on the option itself.
  const source = h('select', { name: 'source' }, [
    ...intake.implemented.map((s) => h('option', { value: s, text: t(`vault.source_${s}`, language) })),
    ...intake.not_built.map((s) =>
      h('option', {
        value: s,
        disabled: '',
        text: `${t(`vault.source_${s}`, language)} — ${t('vault.intake_unavailable', language)}`,
      }),
    ),
  ]);

  // `source` is the item's provenance and it ends up in the export, so it may not be left to the order the
  // payload happened to list the paths in. "Von Hand erfasst" is what a member sitting at this form is
  // actually doing, and a note recorded as "Hochgeladen" would be a false statement about where it came
  // from — on a surface whose whole subject is where things came from (R-151).
  source.value = 'manual';
  let sourceChosen = false;
  source.addEventListener('change', () => { sourceChosen = true; });

  const file = h('input', { type: 'file', name: 'file' });
  // Attaching a file makes it an upload, unless the member has said otherwise — someone photographing a
  // letter picks "capture" and keeps it.
  file.addEventListener('change', () => {
    if (sourceChosen) return;
    source.value = file.files && file.files.length ? 'upload' : 'manual';
  });

  const notes = h('textarea', { name: 'notes', rows: '3' });
  const expiry = h('input', { type: 'date', name: 'expiry_date' });

  // R-041. Replacing an earlier item is choosing it here; there is no edit control anywhere on this
  // surface, because there is no operation on the server that would overwrite a row.
  const supersedes = h('select', { name: 'supersedes_id' }, [
    h('option', { value: '', text: t('vault.supersedes_none', language) }),
    ...items.map((item) =>
      h('option', { value: item.id, text: `${item.title} (${t('vault.version', language)} ${item.version})` }),
    ),
  ]);

  const error = h('div', { class: 'notice error', hidden: '' });

  return h('form', {
    class: 'position-form',
    onSubmit: async (event) => {
      event.preventDefault();
      error.setAttribute('hidden', '');

      let contentBase64 = null;
      try {
        if (file.files && file.files[0]) contentBase64 = await readAsBase64(file.files[0]);
      } catch (readError) {
        error.textContent = String(readError);
        error.removeAttribute('hidden');
        return;
      }

      try {
        await createVaultItem({
          kind: kind.value,
          title: title.value.trim(),
          source: source.value,
          // R-153: no bytes is a legitimate item, so this is null rather than an empty string, and the
          // form does not require a file to submit.
          content_base64: contentBase64,
          expiry_date: expiry.value || null,
          notes: notes.value.trim() || null,
          supersedes_id: supersedes.value || null,
        });
        onSaved();
      } catch (err) {
        // 501 is the unbuilt intake path (A48). The server's own sentence is shown: it explains that the
        // path is undecided rather than blaming the member for a gap in the product.
        error.textContent = err instanceof ApiError ? err.detail || String(err.status) : String(err);
        error.removeAttribute('hidden');
      }
    },
  }, [
    h('h1', { text: t('vault.add_title', language), style: 'font-size:1.2rem' }),
    field(t('vault.add_name', language), title),
    field(t('vault.add_kind', language), kind, t('vault.add_kind_hint', language)),
    field(t('vault.add_file', language), file, t('vault.add_file_hint', language)),
    field(t('vault.add_notes', language), notes, t('vault.add_notes_hint', language)),
    field(t('vault.add_expiry', language), expiry, t('vault.add_expiry_hint', language)),
    h('details', { class: 'tags' }, [
      h('summary', { text: t('vault.add_more', language) }),
      h('p', { class: 'field-hint', text: t('vault.intake_note', language) }),
      field(t('vault.add_source', language), source),
      field(t('vault.add_supersedes', language), supersedes, t('vault.add_supersedes_hint', language)),
    ]),
    error,
    h('div', { class: 'actions' }, [
      h('button', { type: 'submit', class: 'primary' }, [t('vault.save', language)]),
    ]),
  ]);
}

/** Fetch the payload. Kept here so the surface owns its own data shape, as `grid.js` does. */
// A11: the vault is the token's member's. See `app/api.js`.
export function load() {
  return getVault();
}

export function render(container, payload, { memberId, language, onChanged }) {
  clear(container);

  container.append(
    h('span', { class: 'lbl', text: t('vault.eyebrow', language) }),
    h('h1', { text: t('vault.title', language) }),
    h('p', { class: 'lede', text: t('vault.lede', language) }),
  );

  const list = h('div', { class: 'grid' });
  if (payload.items.length) {
    for (const item of payload.items) list.append(itemNode(item, language));
  } else {
    // Not "no data". What would go here, in the words of what the vault is for — the same rule R-110 sets
    // for an empty grid cell.
    list.append(h('p', { class: 'cell-prompt', text: t('vault.empty', language) }));
  }
  container.append(list);

  container.append(
    addForm({
      language,
      intake: payload.intake,
      items: payload.items,
      onSaved: onChanged,
    }),
  );

  container.append(exportSection(memberId, language));
}
