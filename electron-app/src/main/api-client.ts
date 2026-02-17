import axios, { AxiosInstance, AxiosResponse } from 'axios';

export class ApiClient {
  private client: AxiosInstance;
  private baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
    this.client = axios.create({
      baseURL: baseUrl,
      timeout: 10000,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }

  async get(endpoint: string, token?: string, params?: any): Promise<AxiosResponse> {
    const headers: any = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    return this.client.get(endpoint, { headers, params });
  }

  async post(endpoint: string, data: any, token?: string): Promise<AxiosResponse> {
    const headers: any = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    return this.client.post(endpoint, data, { headers });
  }

  async put(endpoint: string, data: any, token?: string): Promise<AxiosResponse> {
    const headers: any = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    return this.client.put(endpoint, data, { headers });
  }

  async delete(endpoint: string, token?: string): Promise<AxiosResponse> {
    const headers: any = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    return this.client.delete(endpoint, { headers });
  }
}
