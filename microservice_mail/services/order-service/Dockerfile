# Use a slim Python image for a smaller footprint
FROM python:3.9-slim

# Set the working directory inside the container
WORKDIR /app

# Copy the requirements file using the correct path from the build context
COPY services/order-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application file using the correct path
COPY services/order-service/app.py .

# Copy the shared directory from the build context
COPY shared ./shared

# Expose the application port
EXPOSE 5001

# Run the application
CMD ["python", "app.py"]
