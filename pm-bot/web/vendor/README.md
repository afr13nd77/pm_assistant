# vendor/

Place `vue.global.prod.js` here for offline use.

Download Vue 3.4+ production build from:
https://unpkg.com/vue@3/dist/vue.global.prod.js

HTML files use CDN fallback:
```html
<script src="https://unpkg.com/vue@3/dist/vue.global.prod.js"></script>
```

If the local file exists, pages will load it first. Otherwise the CDN link is used.
