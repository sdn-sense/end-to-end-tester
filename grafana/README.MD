# How to use dashboard.json

To use dashboard.json, you need to replace 2 variables inside the json:

REPLACEME_TITLE - replace with your own title

```bash
sed -i '' 's/REPLACEME_TITLE/Your Custom Title/g' dashboard.json
```

REPLACEME_DATASOURCE - replace with your datasource uid. To retrieve your datasource uid, go to Grafana Datasources and edit the datasource. You will see uid in URL, e.g.:

```html
https://autogole-grafana.nrp-nautilus.io/datasources/edit/efbb7f6d-3710-4590-a2ec-fd3c74d01e60
```

take `efbb7f6d-3710-4590-a2ec-fd3c74d01e60` and change it `your-datasource-uid` with new uid.

```bash
sed -i '' 's/REPLACEME_DATASOURCE/your-datasource-uid/g' dashboard.json
```

Once replaced, upload it to grafana.
