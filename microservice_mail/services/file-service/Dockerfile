# Use a slim Python image for a smaller footprint
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file using the correct path from the build context
COPY services/file-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application file using the correct path
COPY services/file-service/app.py .

# Copy the shared directory from the build context
COPY shared ./shared

# Expose the application port
EXPOSE 5002

# Run the application
CMD ["python", "app.py"]
