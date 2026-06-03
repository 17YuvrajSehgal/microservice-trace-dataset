# Efficient System Behavior Analysis using Language Models

LMAT (Language Model–based Adaptive Tracing) is a research framework for adaptive, low-overhead observability.  
It models kernel-level event streams (sequence and duration), detects behavioral change, escalates tracing granularity in real time, and produces lightweight root-cause signals.

> 📄 Paper: _LMAT: Language Model–based Adaptive Tracing for Efficient System Observability_   
> 📦 Dataset: Fournier et al. benchmark + LMAT duration-centric extensions

---

## Key Features

- **Adaptive tracing**: raise/lower trace detail on live deviation
- **Multi-task modeling**: next-event + duration prediction
- **Root-cause hints**: error vectors & top-attribution events
- **Operator feedback**: label-once via clustering of benign novelties
- **Practical footprint**: 1M-param LSTM and BERT runs on CPU or modest GPU


