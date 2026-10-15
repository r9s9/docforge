// The privacy policy of the hosted service (app.docforge.live), exactly as it is
// published at https://docforge.live/privacy/. Sign-up shows it in a dialog,
// and a new account records the version it accepted (PRIVACY_VERSION).
//
// Source of truth: lib/markup/privacy.ts in the docforge-website repo. When that
// page changes, copy its <article> body here and update the date and version.
//
// Running your own copy of DocForge? This policy does not cover it. Replace the
// text below with your own policy before you let other people sign up.

export const PRIVACY_URL = "https://docforge.live/privacy/";
export const PRIVACY_UPDATED = "October 15, 2026";
export const PRIVACY_VERSION = "2026-10-15";

export const PRIVACY_HTML = `
  <h2>Who is responsible</h2>
  <p>This policy covers the website docforge.live and the hosted app at app.docforge.live. DocForge is a free, non-commercial, open-source prototype. For anything about your data, contact us at <a href="mailto:support@docforge.live">support@docforge.live</a>.</p>

  <h2>Please don't upload confidential documents</h2>
  <p>The hosted app is a prototype for trying DocForge out. Please don't upload confidential documents or documents containing other people's personal data. For real documents, run your own copy from the <a href="https://github.com/r9s9/docforge" target="_blank" rel="noopener">source code on GitHub</a>. Your own copy runs on your infrastructure and is not covered by this policy.</p>

  <h2>Visiting the website</h2>
  <p>The website is hosted by Vercel. When you open a page, Vercel's servers process technical data that every browser sends: your IP address, the date and time, the page requested, and your browser and operating system. This is needed to deliver the pages and to keep the site secure. Legal basis: our legitimate interest in a working, secure website (Art. 6(1)(f) GDPR). Vercel keeps these logs only for a short period under its own retention rules.</p>
  <p>Fonts and scripts are served from docforge.live itself. The website does not contact Google or any other third-party service, uses no analytics and no tracking, and sets no cookies.</p>

  <h2>Using the hosted app</h2>
  <p>When you create an account and use the app, we process:</p>
  <ul>
  <li>Your email address and password, for signing in. Authentication is handled by Supabase; we never see your password.</li>
  <li>The documents you upload (including documents for compliance checks), the templates and projects you create, and the documents DocForge generates for you.</li>
  <li>AI provider keys you add in Settings. They are stored server-side and are write-only: the app never returns them to the browser.</li>
  <li>Token and cost figures for each AI action, and how many of your free AI actions you have used.</li>
  <li>The same technical log data as for the website.</li>
  </ul>
  <p>Legal basis: providing the app you signed up for (Art. 6(1)(b) GDPR); for log data, our legitimate interest in a secure service (Art. 6(1)(f) GDPR). An email address is required to create an account; without one you can't use the hosted app.</p>

  <h2>AI processing</h2>
  <p>Every account includes 10 free AI actions. During those actions, the content of your document is sent to our AI provider, Anthropic (Claude Haiku 5.5). After that, content is sent to an AI provider only if you connect your own key, under your agreement with that provider. With AI off, processing is deterministic and nothing is sent to an AI provider. We do not use your documents to train models. Legal basis: providing the app (Art. 6(1)(b) GDPR).</p>

  <h2>Emailing us</h2>
  <p>If you write to support@docforge.live, we process your email address and message to answer you (Art. 6(1)(b) or (f) GDPR). Our mailbox is hosted by IONOS in Germany. We delete messages once they are no longer needed.</p>

  <h2>Recipients and processors</h2>
  <p>These providers process data on our behalf under data processing terms (Art. 28 GDPR):</p>
  <ul>
  <li>Vercel Inc., USA: hosting of the website and the app.</li>
  <li>Supabase Inc., USA: database, file storage and sign-in.</li>
  <li>Anthropic PBC, USA: AI processing during your 10 free AI actions.</li>
  <li>IONOS SE, Germany: our email.</li>
  </ul>
  <p>If you connect your own AI key, the provider you choose receives document content under your own agreement with them.</p>

  <h2>Transfers outside the EU</h2>
  <p>Vercel, Supabase and Anthropic are US companies, so data may be processed in the USA. These transfers rely on the EU-US Data Privacy Framework where the company is certified under it, and otherwise on the EU standard contractual clauses in its data processing terms (Art. 46(2)(c) GDPR).</p>

  <h2>How long we keep data</h2>
  <ul>
  <li>Account data, templates, projects and AI usage figures: until you delete them or your account.</li>
  <li>Generated documents: deleted automatically within 14 days. Storage is shared and capped, so the oldest are deleted sooner when it fills up. There is no list of past generated documents, so download what you need when you generate it.</li>
  <li>Documents uploaded for compliance checks: until you delete your account. Deleting a template does not remove them.</li>
  <li>Server logs: a short period, under Vercel's retention rules.</li>
  </ul>
  <p>You can delete your account with all of its data yourself in Settings.</p>

  <h2>Your rights</h2>
  <p>You have the right to access your data (Art. 15 GDPR), to have it corrected (Art. 16), deleted (Art. 17) or its processing restricted (Art. 18), and to receive it in a portable format (Art. 20). Most of your data you can view and delete yourself in the app; for anything else, email us. You also have the right to complain to a data protection supervisory authority (Art. 77 GDPR), for example the one where you live or the one responsible for us.</p>

  <h2>Right to object</h2>
  <div class="callout">
  <p><strong>Where we process data based on our legitimate interest (Art. 6(1)(f) GDPR), you can object at any time, for reasons arising from your particular situation (Art. 21 GDPR).</strong> We then stop, unless we have compelling legitimate grounds that override your interests, or the processing is needed for legal claims. Email us to object.</p>
  </div>

  <h2>Local storage, no cookies</h2>
  <p>Neither the website nor the app sets cookies. The website stores your theme choice in your browser's local storage. The app keeps your sign-in session and interface settings (theme, menu order and pins, tutorial progress, expanded cards) there too. This is strictly necessary for features you use, so no consent is required (§ 25(2) no. 2 TDDDG).</p>

  <h2>No automated decisions</h2>
  <p>We do not make automated decisions about you, including profiling, within the meaning of Art. 22 GDPR. The AI only processes the content of your documents.</p>

  <h2>Changes</h2>
  <p>We post updates to this policy on this page, with the date above.</p>
`;
