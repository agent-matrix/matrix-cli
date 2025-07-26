# Examples

## Search & Install PDF Summarizer Agent

```bash
matrix search "summarize pdfs" --type agent --capabilities pdf,summarize
matrix install agent:pdf-summarizer@1.4.2 --target ./apps/pdf-bot
```

## Use in Scripts
```bash
# Bash script example
results=$(matrix search "ocr table" --type tool --json)
tool_id=$(echo "$results" | jq -r '.items[0].id')
matrix install "$tool_id" --target ./apps/data-pipeline
```
