# Local Models

This directory stores local model files used by `RAGwork/embedding.py` and `RAGwork/rerank.py`.

Required layout:

```text
data/model/
  text2vec-base-chinese/
  bge-reranker-large/
```

Model usage:

```text
text2vec-base-chinese  embedding retrieval
bge-reranker-large     rerank
```

The model directories are ignored by Git because model weights are large and machine-specific.

Prepare the models from a local copy or a model registry, then place them under `data/model/`.

Example:

```bash
cp -R /path/to/text2vec-base-chinese data/model/
cp -R /path/to/bge-reranker-large data/model/
```

Then run:

```bash
/opt/anaconda3/envs/Tagent/bin/python RAGwork/embedding.py
/opt/anaconda3/envs/Tagent/bin/python RAGwork/rerank.py
```
