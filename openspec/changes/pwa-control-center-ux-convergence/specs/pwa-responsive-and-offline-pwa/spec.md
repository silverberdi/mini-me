## MODIFIED Requirements

### Requirement: Multi-Breakpoint Responsive Layout
The PWA SHALL preserve the approved dark, high-density operational visual language and consistent information model while adapting interaction to desktop, tablet and mobile. It SHALL prevent horizontal overflow, clipping of essential content, inaccessible controls and misleading data compression at 1440×900, 1024×768, 768×1024, 390×844 and 360×800. Desktop SHALL prioritize the active/most significant Run with operational panels and contextual drawers; tablet SHALL support touch-capable master-detail/split operation; mobile SHALL prioritize supervision and human attention in a compact single-column experience and SHALL NOT reproduce desktop tables or expose dangerous direct execution controls.

#### Scenario: Desktop high-density Control Center
Given the browser viewport is 1440×900 and authoritative data includes an active Run and queued/attention work
When the Control Center loads
Then the active Run, pipeline, queue/blocked reasons, attention, activity and provider/metrics panels SHALL remain navigable in the approved hierarchy without destructive truncation or horizontal page overflow.

#### Scenario: View PWA on ultrawide desktop
Given a wide desktop browser viewport and authoritative operational data
When the PWA loads
Then it SHALL use the desktop control-center hierarchy without horizontal overflow or relying on fixed reference-image metrics.

#### Scenario: Tablet master-detail operation
Given the browser viewport is 1024×768 or 768×1024
When the operator selects an execution or attention item
Then the master list and relevant detail SHALL remain operable in a split or master-detail layout with touch targets approximately 44 CSS pixels or larger where practical.

#### Scenario: Mobile supervision and pause
Given the browser viewport is 390×844 or 360×800 and the scheduler is intentionally paused or the Run requires attention
When the operator opens the Control Center
Then the interface SHALL prioritize current state, latest activity, next work, blocker and consequences
And the pause surface SHALL offer “Ver condiciones de reanudación” rather than an impulsive scheduler resume action.

#### Scenario: View PWA on mobile device
Given the browser viewport is 390×844 or 360×800
When the PWA Control Center loads
Then the view SHALL collapse into the approved mobile supervision layout with reachable navigation and no desktop table overflow.

#### Scenario: Status remains legible without color
Given the UI is viewed with reduced color perception, keyboard navigation or assistive technology
When operational states and focus move across the interface
Then every status SHALL have a text label and accessible name
And focus SHALL be visible and dialogs SHALL preserve sensible focus order.

### Requirement: Service Worker Static Shell Caching and Offline Resilience
The service worker SHALL cache only same-origin, explicitly allowlisted safe static application-shell resources. It SHALL NOT read from or write to CacheStorage for any `/api/*` path, authenticated endpoint (including `/api/v1/auth/*`), Control Plane read or mutation, action result, operational evidence, session data, personal telemetry, or non-GET request. It SHALL NOT serve a cached API response after a network failure or queue a mutation while offline. When authentication or connectivity is unavailable, the shell MAY remain available but SHALL present a clear read-only degraded state; operational data SHALL be marked stale/unavailable until its own authenticated request succeeds and SHALL NOT be exposed from a previous browser session.

#### Scenario: Backend disconnection handling
Given an authenticated session loses connectivity after initial load
When the next read request fails
Then the shell SHALL remain navigable where assets are cached
And mark operational state stale/unavailable, prevent mutation submission, and explain that no offline action was queued.

#### Scenario: Reconnection refresh
Given the UI is in an offline or stale state and connectivity returns
When a fresh API request succeeds
Then the UI SHALL replace stale projections with the new authoritative response and its observation time
And clear the degraded indicator only for data whose refresh succeeded.

#### Scenario: Automatic reconnection recovery
Given the PWA displays stale/offline state for one or more panels
When their respective authenticated reads succeed again
Then those panels SHALL refresh and clear their degraded state
And other panels SHALL remain stale until their own reads succeed.

#### Scenario: Authentication expires offline
Given a previously authenticated browser has cached the static shell but no valid current session
When it opens offline or receives 401/403
Then it SHALL NOT expose cached operational data or mutation capability
And SHALL explain that authentication/connectivity must be restored.

#### Scenario: Authenticated APIs and Control Plane are never cached
Given an authenticated session reads `/api/*`, including `/api/v1/auth/*`, or submits a Control Plane action
When the service worker handles successful, rejected, or failed responses
Then it SHALL neither store nor return those request/response pairs through CacheStorage
And an offline request SHALL be reported unavailable without replaying a prior response or mutation.

#### Scenario: Operational cache cannot cross browser sessions
Given one browser session loaded private operational data and then logs out or is replaced by a different operator session
When another session opens the cached application shell while offline
Then it SHALL see no operational data from the prior session
And all operational panels SHALL remain unavailable until separately authenticated fresh reads succeed.

#### Scenario: Only safe static resources are cached
Given the service worker installs or fetches same-origin resources
When a request is for an allowlisted static shell asset versus a dynamic route, API path, cross-origin URL, or non-GET method
Then it MAY cache only the allowlisted static asset
And SHALL bypass CacheStorage for every other request.
