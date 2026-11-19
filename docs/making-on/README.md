# Making on Frappe Cloud v2

> *Know the ground before you hunt.*
> The illustrated page is [`index.html`](index.html), published at
> <https://bthuner.github.io/dodock-wolf/making-on/>. It is not linked from the docs site and asks
> search engines not to index it.

The [making-of](../making-of/README.md) tells how Dodock Wolf was shaped. The making-on tells what
it stands on since [#136](https://github.com/bthuner/dodock-wolf/issues/136): Frappe Cloud v2, read
from the code of its applications on 19 November 2026. Nothing in it was checked on a running
server yet.

| Chapter | What it shows |
|---|---|
| 01 Le virage | Why Wolf stopped building what Frappe builds |
| 02 La carte | The six applications on three planes, and the 26 links between them (pick an application or a kind of link) |
| 03 Les habitants | What each application owns |
| 04 Les clés | The chain of public keys, and how long each credential lives |
| 05 Les trajets | Six flows, hop by hop: a server is created, a hostname is routed, a number is measured, a person is paged, a customer is told, an image is built |
| 06 Ce qui sort | The eight metrics a customer's server sends, and what stays on it |
| 07 L'angle mort | Who sees what: Atlas, Datum and Beacon, Central, the Wolf Agent |
| 08 Les ponts | The bridges, cheapest first, and the closed ones |
| 09 Les corrections | What the code corrected in #133, #134, #135 and in Frappe's own documents |
| 10 Le terrain | What to check on a real server |

The text behind it, with every route, header and token, is the unlisted section of the docs site:
[`docs-site/content/en/7.internals/`](../../docs-site/content/en/7.internals/) (French in
`content/fr/7.internals/`), served at `/internals`.

## Repositories read

| Repository | Commit |
|---|---|
| frappe/central | `5027a0c` |
| frappe/atlas | `31aa231` |
| frappe/cargo | `0f18a8a` |
| frappe/pilot | `77acd72` |
| frappe/datum | `a08c555` |
| frappe/beacon | `d83a532` |
| frappe/cloudtoolkit, marketplace, one-click-templates, grove, pathway, suite_cloud | `d51be63`, `824b64a`, `b342c95`, `e1dcd85`, `3f91aca`, `9e118db` |

## Editing

The page is one file with no build step. It uses the making-of's tokens
([`../making-of/brand.md`](../making-of/brand.md)) and its assets (`../making-of/assets/`), which
the Pages workflow publishes next to it. The map is inline SVG: each link is a
`<g class="edge" data-kind data-ends>` with a twin `<li data-edge>` in the list under the map, so a
link added to one is added to the other. When Frappe's repositories move, update the commits here,
in the page's colophon and in `docs-site/content/{en,fr}/7.internals/1.index.md`.
