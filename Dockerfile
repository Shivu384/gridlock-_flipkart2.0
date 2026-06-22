FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by OpenCV and EasyOCR
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js for building the React frontend
RUN curl -fsSL https://deb.nodesource.com/setup_18.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy and build the frontend
COPY frontend/ ./frontend/
RUN cd frontend && npm ci && npm run build

# Copy the backend code
COPY backend/ ./backend/
COPY best.pt ./best.pt

# Set environment variable to run on port 7860 (Hugging Face standard)
ENV PORT=7860
EXPOSE 7860

# Run the FastAPI server
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "7860"]
