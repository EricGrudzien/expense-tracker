FROM public.ecr.aws/lambda/python:3.12

# Install scientific/charting libraries
RUN pip install --no-cache-dir \
    matplotlib==3.9.2 \
    numpy==2.1.3 \
    pandas==2.2.3 \
    --target "${LAMBDA_TASK_ROOT}"

# Use non-interactive matplotlib backend (no display needed in Lambda)
ENV MPLBACKEND=Agg

COPY lambda_function.py ${LAMBDA_TASK_ROOT}

CMD ["lambda_function.handler"]
