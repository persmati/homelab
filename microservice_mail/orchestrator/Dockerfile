# Use a slim Python image for a smaller footprint
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file and install dependencies
COPY orchestrator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application files
COPY orchestrator/app.py .

# Copy the shared directory (relative to the build context)
COPY shared ./shared

# Expose the application port
EXPOSE 5000

# Run the application
CMD ["python", "app.py"]
