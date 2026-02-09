# Ollama Inference Test

Test and benchmark the local Ollama inference server.

## Instructions

```text
skill_run("ollama_inference_test", '{"action": "", "model": "", "prompt": "", "instances": ""}')
```

## What It Does

Test and benchmark the local Ollama inference server.

Features:
- Check Ollama server status and loaded models
- Pull new models
- Run inference tests with custom prompts
- Benchmark response times
- Test classification and embedding endpoints
- Restart Ollama service if needed

Uses: ollama_status, ollama_test, ollama_generate,
ollama_classify, systemctl_status,
systemctl_restart, curl_timing

## Parameters

| Parameter | Description | Required |
|-----------|-------------|----------|
| `action` | Action to perform (default: status) | No |
| `model` | Model name for testing (default: llama3.2:3b) (default: llama3.2:3b) | No |
| `prompt` | Test prompt for inference (default: Explain Kubernetes pods in one paragraph.) | No |
| `instances` | Number of test iterations for benchmarking (default: 3) | No |
