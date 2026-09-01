from __future__ import annotations

import html


def privacy_policy_body(operator_contact: str) -> str:
    contact = html.escape(operator_contact or "the server operator")
    return f"""
    <header><h1>Privacy Policy</h1><p>Phenikaa Calendar Server</p></header>
    <main>
    <section>
    <p>This service helps signed-in Phenikaa users export their academic calendar and, if they choose, sync it one way into Google Calendar.</p>
    <h2>Information the server uses</h2>
    <ul>
    <li>OIDC sign-in information from the configured identity provider, including the subject identifier and display name used to create the local account and browser session.</li>
    <li>Phenikaa session information captured after you sign in through the streamed browser: your Phenikaa <code>userId</code>, an encrypted <code>tokenJWT</code>, and retained browser cookies in the per-session browser profile so the server can refresh the session without storing your password.</li>
    <li>Academic calendar records returned by Phenikaa for the selected date range, including course, exam, time, room, lecturer, section, and attendance details present in the source data.</li>
    <li>Generated JSON and ICS calendar exports for each session.</li>
    <li>If you connect Google Calendar, encrypted Google access and refresh tokens, token metadata, sync status, and links between Phenikaa source events and Google event IDs.</li>
    </ul>
    <h2>How information is used</h2>
    <p>The server uses OIDC data to authenticate you, Phenikaa session data to fetch your academic calendar, retained browser cookies to refresh Phenikaa access, and calendar records to create exports and dashboard status. Google tokens are used only to perform the optional Google Calendar sync that you start by connecting Google.</p>
    <p>Fresh Google connections request only <code>https://www.googleapis.com/auth/calendar.app.created</code>. Sessions upgraded from the earlier primary-calendar sync request temporary <code>https://www.googleapis.com/auth/calendar.events</code> only while primary cleanup is pending. Sync is one way from Phenikaa to a dedicated Google calendar created by this app. The server creates new linked Google events, updates previously linked Google events, and deletes stale Google events only when they were previously linked by this app and disappeared from the selected Phenikaa range. Upgraded legacy cleanup GET-verifies each stored primary event still has the matching app private marker before deleting it, removes absent 404/410 links locally, then revokes the broad legacy token after dedicated-calendar reconcile. The service does not modify or delete unrelated Google Calendar events.</p>
    <h2>Sharing and outbound services</h2>
    <p>The server does not sell personal data, use advertising, or add analytics. It makes outbound calls only as needed to the configured OIDC provider, Phenikaa services, and Google OAuth/Calendar APIs. Calendar data is not intentionally shared with other services.</p>
    <h2>Retention and deletion</h2>
    <p>Server state is retained while your account and sessions remain configured, including the SQLite database, generated exports, and browser profiles. Deleting a Phenikaa session from the dashboard removes that session's database row, generated exports, Google connection rows and event links through database cascading, and its retained browser profile. Disconnecting Google revokes the Google token when Google accepts the revocation request and removes the local Google connection. Logging out clears only the application session cookie in your browser.</p>
    <h2>Google API Limited Use</h2>
    <p>This app's use and transfer of information received from Google APIs adheres to the Google API Services User Data Policy, including the Limited Use requirements. Google Calendar data and tokens are used only to provide or improve the user-facing calendar sync described above, are not used for advertising, and are not sold.</p>
    <h2>Contact</h2>
    <p>Contact: {contact}</p>
    </section>
    </main>"""


def terms_body(operator_contact: str) -> str:
    contact = html.escape(operator_contact or "the server operator")
    return f"""
    <header><h1>Terms of Service</h1><p>Phenikaa Calendar Server</p></header>
    <main>
    <section>
    <p>By using this server, you agree to use it only for your own Phenikaa academic calendar data or data you are authorized to access. This is an unofficial service and is not affiliated with or endorsed by Phenikaa University or Google.</p>
    <h2>What the service does</h2>
    <p>The service authenticates users through the configured OIDC provider, lets each user create Phenikaa calendar sessions, captures the Phenikaa <code>userId</code> and <code>tokenJWT</code> after the user signs in, stores the token encrypted, keeps browser cookies in a per-session browser profile, fetches academic calendar data for the chosen date range, and writes JSON and ICS exports.</p>
    <p>Google Calendar integration is optional. Fresh connections request only <code>https://www.googleapis.com/auth/calendar.app.created</code> and perform one-way sync from Phenikaa to a dedicated Google calendar created by this app. Upgraded legacy sessions request temporary <code>https://www.googleapis.com/auth/calendar.events</code> only while verified primary cleanup is pending, then revoke that broad token and reconnect app-only. It creates, updates, and deletes only Google events linked by this app; upgraded legacy cleanup verifies the matching app private marker before deleting stored primary event IDs. It does not provide two-way sync and does not manage unrelated Google events.</p>
    <h2>Your responsibilities</h2>
    <ul>
    <li>Use an account and Google Calendar that you control or are authorized to connect.</li>
    <li>Keep access to this server and its state directory restricted to trusted operators.</li>
    <li>Check critical dates, exam times, rooms, and attendance requirements against official Phenikaa records before relying on them.</li>
    <li>Disconnect Google or delete a session when you no longer want the service to retain or sync that session.</li>
    </ul>
    <h2>Limitations</h2>
    <p>The service depends on the configured identity provider, Phenikaa portal/API behavior, retained browser cookies, Google OAuth, and Google Calendar APIs. Those services can change, be unavailable, or reject requests. The service is provided as-is, without warranties, for convenience only and does not replace official Phenikaa records.</p>
    <h2>Data practices</h2>
    <p>The service does not sell data, show advertising, or include analytics. It makes outbound requests only to the configured OIDC provider, Phenikaa services, and Google OAuth/Calendar APIs needed for authentication, calendar export, token refresh, revocation, and optional sync. Its use of Google API information adheres to the Google API Services User Data Policy, including the Limited Use requirements.</p>
    <h2>Changes and contact</h2>
    <p>The operator may update these terms when the deployed service changes. Contact: {contact}</p>
    </section>
    </main>"""
