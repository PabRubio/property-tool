# Public commercial form integration

Move the approved residential/commercial form from the temporary local page into `web/public/index.html`. Preserve the public page design, Un-static native POST, version-2 JSON export, session draft recovery, confirmation, terms and privacy. Retain the latest removal of both grey helper notes. Commercial scope remains one retail, office or industrial unit in England.

Restore the dashboard header link to `https://lacewinganalytics.co.uk/#contact`, without changing its text. Remove `/brief`, its dedicated assets and obsolete browser harness. Preserve all commercial backend and report work and existing records.

Approach: copy the approved form body and its conditional-field/payload functions into the existing embedded public form script. Keep the public transport and success handling. A public connection to the local dashboard would require a different architecture and is outside this request; keeping duplicate temporary forms would leave maintenance work the user explicitly asked to remove.

Verification: public browser exports and intercepted email payloads must match for residential, area and all three commercial types; import those payloads through the real local records API using temporary records. Check switching types, unknown values, draft recovery, validation and responsive layout. No deployment, outgoing email, paid calls or customer-data changes.
