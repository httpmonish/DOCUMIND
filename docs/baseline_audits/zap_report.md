# ZAP Scanning Report

ZAP by [Checkmarx](https://checkmarx.com/).


## Summary of Alerts

| Risk Level | Number of Alerts |
| --- | --- |
| High | 0 |
| Medium | 2 |
| Low | 5 |
| Informational | 3 |




## Insights

| Level | Reason | Site | Description | Statistic |
| --- | --- | --- | --- | --- |
| Info | Informational | http://host.docker.internal:8000 | Percentage of responses with status code 2xx | 69 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of responses with status code 3xx | 7 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of responses with status code 4xx | 23 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type application/json | 27 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type image/png | 9 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type image/svg+xml | 9 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type image/x-icon | 9 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type text/css | 9 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type text/html | 18 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with content type text/javascript | 18 % |
| Info | Informational | http://host.docker.internal:8000 | Percentage of endpoints with method GET | 100 % |
| Info | Informational | http://host.docker.internal:8000 | Count of total endpoints | 11    |







## Alerts

| Name | Risk Level | Number of Instances |
| --- | --- | --- |
| Content Security Policy (CSP) Header Not Set | Medium | 3 |
| Sub Resource Integrity Attribute Missing | Medium | Systemic |
| Cross-Domain JavaScript Source File Inclusion | Low | 2 |
| Cross-Origin-Embedder-Policy Header Missing or Invalid | Low | 3 |
| Cross-Origin-Opener-Policy Header Missing or Invalid | Low | 3 |
| Cross-Origin-Resource-Policy Header Missing or Invalid | Low | Systemic |
| Permissions Policy Header Not Set | Low | 5 |
| Information Disclosure - Suspicious Comments | Informational | 7 |
| Modern Web Application | Informational | 2 |
| Non-Storable Content | Informational | Systemic |




## Alert Detail



### [ Content Security Policy (CSP) Header Not Set ](https://www.zaproxy.org/docs/alerts/10038/)



##### Medium (High)

### Description

Content Security Policy (CSP) is an added layer of security that helps to detect and mitigate certain types of attacks, including Cross Site Scripting (XSS) and data injection attacks. These attacks are used for everything from data theft to site defacement or distribution of malware. CSP provides a set of standard HTTP headers that allow website owners to declare approved sources of content that browsers should be allowed to load on that page — covered types are JavaScript, CSS, HTML frames, fonts, images and embeddable objects such as Java applets, ActiveX, audio and video files.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat.html
  * Node Name: `http://host.docker.internal:8000/app/chat.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``


Instances: 3

### Solution

Ensure that your web server, application server, load balancer, etc. is configured to set the Content-Security-Policy header.

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP ](https://developer.mozilla.org/en-US/docs/Web/HTTP/Guides/CSP)
* [ https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html ](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html)
* [ https://www.w3.org/TR/CSP/ ](https://www.w3.org/TR/CSP/)
* [ https://w3c.github.io/webappsec-csp/ ](https://w3c.github.io/webappsec-csp/)
* [ https://web.dev/articles/csp ](https://web.dev/articles/csp)
* [ https://caniuse.com/#feat=contentsecuritypolicy ](https://caniuse.com/#feat=contentsecuritypolicy)
* [ https://content-security-policy.com/ ](https://content-security-policy.com/)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 15

#### Source ID: 3

### [ Sub Resource Integrity Attribute Missing ](https://www.zaproxy.org/docs/alerts/90003/)



##### Medium (High)

### Description

The integrity attribute is missing on a script or link tag served by an external server. The integrity tag prevents an attacker who have gained access to this server from injecting a malicious content.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&amp;family=JetBrains+Mono:wght@400;500;600&amp;display=swap" rel="stylesheet">`
  * Other Info: ``
* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet">`
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat.html
  * Node Name: `http://host.docker.internal:8000/app/chat.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">`
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&amp;family=JetBrains+Mono:wght@400;500;600&amp;display=swap" rel="stylesheet">`
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<link href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" rel="stylesheet">`
  * Other Info: ``

Instances: Systemic


### Solution

Provide a valid integrity attribute to the tag.

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Subresource_Integrity ](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Subresource_Integrity)


#### CWE Id: [ 345 ](https://cwe.mitre.org/data/definitions/345.html)


#### WASC Id: 15

#### Source ID: 3

### [ Cross-Domain JavaScript Source File Inclusion ](https://www.zaproxy.org/docs/alerts/10017/)



##### Low (Medium)

### Description

The page includes one or more script files from a third-party domain.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: `https://cdn.tailwindcss.com`
  * Attack: ``
  * Evidence: `<script src="https://cdn.tailwindcss.com"></script>`
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: `https://cdn.tailwindcss.com`
  * Attack: ``
  * Evidence: `<script src="https://cdn.tailwindcss.com"></script>`
  * Other Info: ``


Instances: 2

### Solution

Ensure JavaScript source files are loaded from only trusted sources, and the sources can't be controlled by end users of the application.

### Reference



#### CWE Id: [ 829 ](https://cwe.mitre.org/data/definitions/829.html)


#### WASC Id: 15

#### Source ID: 3

### [ Cross-Origin-Embedder-Policy Header Missing or Invalid ](https://www.zaproxy.org/docs/alerts/90004/)



##### Low (Medium)

### Description

Cross-Origin-Embedder-Policy header is a response header that prevents a document from loading any cross-origin resources that don't explicitly grant the document permission (using CORP or CORS).

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: `Cross-Origin-Embedder-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat.html
  * Node Name: `http://host.docker.internal:8000/app/chat.html`
  * Method: `GET`
  * Parameter: `Cross-Origin-Embedder-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: `Cross-Origin-Embedder-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``


Instances: 3

### Solution

Ensure that the application/web server sets the Cross-Origin-Embedder-Policy header appropriately, and that it sets the Cross-Origin-Embedder-Policy header to 'require-corp' for documents.
If possible, ensure that the end user uses a standards-compliant and modern web browser that supports the Cross-Origin-Embedder-Policy header (https://caniuse.com/mdn-http_headers_cross-origin-embedder-policy).

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy ](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 14

#### Source ID: 3

### [ Cross-Origin-Opener-Policy Header Missing or Invalid ](https://www.zaproxy.org/docs/alerts/90004/)



##### Low (Medium)

### Description

Cross-Origin-Opener-Policy header is a response header that allows a site to control if others included documents share the same browsing context. Sharing the same browsing context with untrusted documents might lead to data leak.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: `Cross-Origin-Opener-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat.html
  * Node Name: `http://host.docker.internal:8000/app/chat.html`
  * Method: `GET`
  * Parameter: `Cross-Origin-Opener-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: `Cross-Origin-Opener-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``


Instances: 3

### Solution

Ensure that the application/web server sets the Cross-Origin-Opener-Policy header appropriately, and that it sets the Cross-Origin-Opener-Policy header to 'same-origin' for documents.
'same-origin-allow-popups' is considered as less secured and should be avoided.
If possible, ensure that the end user uses a standards-compliant and modern web browser that supports the Cross-Origin-Opener-Policy header (https://caniuse.com/mdn-http_headers_cross-origin-opener-policy).

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Opener-Policy ](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Opener-Policy)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 14

#### Source ID: 3

### [ Cross-Origin-Resource-Policy Header Missing or Invalid ](https://www.zaproxy.org/docs/alerts/90004/)



##### Low (Medium)

### Description

Cross-Origin-Resource-Policy header is an opt-in header designed to counter side-channels attacks like Spectre. Resource should be specifically set as shareable amongst different origins.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat-drawer.js
  * Node Name: `http://host.docker.internal:8000/app/chat-drawer.js`
  * Method: `GET`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat.html
  * Node Name: `http://host.docker.internal:8000/app/chat.html`
  * Method: `GET`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/favicon.ico
  * Node Name: `http://host.docker.internal:8000/favicon.ico`
  * Method: `GET`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/favicon.svg
  * Node Name: `http://host.docker.internal:8000/favicon.svg`
  * Method: `GET`
  * Parameter: `Cross-Origin-Resource-Policy`
  * Attack: ``
  * Evidence: ``
  * Other Info: ``

Instances: Systemic


### Solution

Ensure that the application/web server sets the Cross-Origin-Resource-Policy header appropriately, and that it sets the Cross-Origin-Resource-Policy header to 'same-origin' for all web pages.
'same-site' is considered as less secured and should be avoided.
If resources must be shared, set the header to 'cross-origin'.
If possible, ensure that the end user uses a standards-compliant and modern web browser that supports the Cross-Origin-Resource-Policy header (https://caniuse.com/mdn-http_headers_cross-origin-resource-policy).

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy ](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Cross-Origin-Embedder-Policy)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 14

#### Source ID: 3

### [ Permissions Policy Header Not Set ](https://www.zaproxy.org/docs/alerts/10063/)



##### Low (Medium)

### Description

Permissions Policy Header is an added layer of security that helps to restrict from unauthorized access or usage of browser/client features by web resources. This policy ensures the user privacy by limiting or specifying the features of the browsers can be used by the web resources. Permissions Policy provides a set of standard HTTP headers that allow website owners to limit which features of browsers can be used by the page such as camera, microphone, location, full screen etc.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/api.js
  * Node Name: `http://host.docker.internal:8000/app/api.js`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat-drawer.js
  * Node Name: `http://host.docker.internal:8000/app/chat-drawer.js`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat.html
  * Node Name: `http://host.docker.internal:8000/app/chat.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: ``
  * Other Info: ``


Instances: 5

### Solution

Ensure that your web server, application server, load balancer, etc. is configured to set the Permissions-Policy header.

### Reference


* [ https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Permissions-Policy ](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Permissions-Policy)
* [ https://developer.chrome.com/blog/feature-policy/ ](https://developer.chrome.com/blog/feature-policy/)
* [ https://scotthelme.co.uk/a-new-security-header-feature-policy/ ](https://scotthelme.co.uk/a-new-security-header-feature-policy/)
* [ https://w3c.github.io/webappsec-feature-policy/ ](https://w3c.github.io/webappsec-feature-policy/)
* [ https://www.smashingmagazine.com/2018/12/feature-policy/ ](https://www.smashingmagazine.com/2018/12/feature-policy/)


#### CWE Id: [ 693 ](https://cwe.mitre.org/data/definitions/693.html)


#### WASC Id: 15

#### Source ID: 3

### [ Information Disclosure - Suspicious Comments ](https://www.zaproxy.org/docs/alerts/10027/)



##### Informational (Medium)

### Description

The response appears to contain suspicious comments which may help an attacker.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `// 1. Append User message bubble`
  * Other Info: `The following pattern was used: \bUSER\b and was detected in likely comment: "// 1. Append User message bubble", see evidence field for the suspicious comment/snippet.`
* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<!-- Query Command Unit -->`
  * Other Info: `The following pattern was used: \bQUERY\b and was detected 2 times, the first in likely comment: "<!-- Query Command Unit -->", see evidence field for the suspicious comment/snippet.`
* URL: http://host.docker.internal:8000/app/api.js
  * Node Name: `http://host.docker.internal:8000/app/api.js`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `// User Authentication Moda`
  * Other Info: `The following pattern was used: \bUSER\b and was detected in likely comment: "// User Authentication Modal & Avatar binding", see evidence field for the suspicious comment/snippet.`
* URL: http://host.docker.internal:8000/app/chat-drawer.js
  * Node Name: `http://host.docker.internal:8000/app/chat-drawer.js`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `// 1. Render User Message`
  * Other Info: `The following pattern was used: \bUSER\b and was detected in likely comment: "// 1. Render User Message", see evidence field for the suspicious comment/snippet.`
* URL: http://host.docker.internal:8000/app/chat.html
  * Node Name: `http://host.docker.internal:8000/app/chat.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `// 1. Render User Message`
  * Other Info: `The following pattern was used: \bUSER\b and was detected in likely comment: "// 1. Render User Message", see evidence field for the suspicious comment/snippet.`
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `// 1. Append User message bubble`
  * Other Info: `The following pattern was used: \bUSER\b and was detected in likely comment: "// 1. Append User message bubble", see evidence field for the suspicious comment/snippet.`
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<!-- Query Command Unit -->`
  * Other Info: `The following pattern was used: \bQUERY\b and was detected 2 times, the first in likely comment: "<!-- Query Command Unit -->", see evidence field for the suspicious comment/snippet.`


Instances: 7

### Solution

Remove all comments that return information that may help an attacker and fix any underlying problems they refer to.

### Reference



#### CWE Id: [ 615 ](https://cwe.mitre.org/data/definitions/615.html)


#### WASC Id: 13

#### Source ID: 3

### [ Modern Web Application ](https://www.zaproxy.org/docs/alerts/10109/)



##### Informational (Medium)

### Description

The application appears to be a modern web application. If you need to explore it automatically then the Client Spider may well be more effective than the standard one.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<a class="font-headline-sm text-headline-sm text-on-surface-variant hover:text-on-surface transition-colors" data-path="architecture" href="#">Architecture</a>`
  * Other Info: `Links have been found that do not have traditional href attributes, which is an indication that this is a modern web application.`
* URL: http://host.docker.internal:8000/app/console/code.html
  * Node Name: `http://host.docker.internal:8000/app/console/code.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `<a class="font-headline-sm text-headline-sm text-on-surface-variant hover:text-on-surface transition-colors" data-path="architecture" href="#">Architecture</a>`
  * Other Info: `Links have been found that do not have traditional href attributes, which is an indication that this is a modern web application.`


Instances: 2

### Solution

This is an informational alert and so no changes are required.

### Reference




#### Source ID: 3

### [ Non-Storable Content ](https://www.zaproxy.org/docs/alerts/10049/)



##### Informational (Medium)

### Description

The response contents are not storable by caching components such as proxy servers. If the response does not contain sensitive, personal or user-specific information, it may benefit from being stored and cached, to improve performance.

* URL: http://host.docker.internal:8000
  * Node Name: `http://host.docker.internal:8000`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `no-store`
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat-drawer.js
  * Node Name: `http://host.docker.internal:8000/app/chat-drawer.js`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `no-store`
  * Other Info: ``
* URL: http://host.docker.internal:8000/app/chat.html
  * Node Name: `http://host.docker.internal:8000/app/chat.html`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `no-store`
  * Other Info: ``
* URL: http://host.docker.internal:8000/favicon.ico
  * Node Name: `http://host.docker.internal:8000/favicon.ico`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `no-store`
  * Other Info: ``
* URL: http://host.docker.internal:8000/favicon.svg
  * Node Name: `http://host.docker.internal:8000/favicon.svg`
  * Method: `GET`
  * Parameter: ``
  * Attack: ``
  * Evidence: `no-store`
  * Other Info: ``

Instances: Systemic


### Solution

The content may be marked as storable by ensuring that the following conditions are satisfied:
The request method must be understood by the cache and defined as being cacheable ("GET", "HEAD", and "POST" are currently defined as cacheable)
The response status code must be understood by the cache (one of the 1XX, 2XX, 3XX, 4XX, or 5XX response classes are generally understood)
The "no-store" cache directive must not appear in the request or response header fields
For caching by "shared" caches such as "proxy" caches, the "private" response directive must not appear in the response
For caching by "shared" caches such as "proxy" caches, the "Authorization" header field must not appear in the request, unless the response explicitly allows it (using one of the "must-revalidate", "public", or "s-maxage" Cache-Control response directives)
In addition to the conditions above, at least one of the following conditions must also be satisfied by the response:
It must contain an "Expires" header field
It must contain a "max-age" response directive
For "shared" caches such as "proxy" caches, it must contain a "s-maxage" response directive
It must contain a "Cache Control Extension" that allows it to be cached
It must have a status code that is defined as cacheable by default (200, 203, 204, 206, 300, 301, 404, 405, 410, 414, 501).

### Reference


* [ https://datatracker.ietf.org/doc/html/rfc7234 ](https://datatracker.ietf.org/doc/html/rfc7234)
* [ https://datatracker.ietf.org/doc/html/rfc7231 ](https://datatracker.ietf.org/doc/html/rfc7231)
* [ https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html ](https://www.w3.org/Protocols/rfc2616/rfc2616-sec13.html)


#### CWE Id: [ 524 ](https://cwe.mitre.org/data/definitions/524.html)


#### WASC Id: 13

#### Source ID: 3


