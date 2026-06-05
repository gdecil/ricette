const axios = require('axios');
const cheerio = require('cheerio');
const { pool } = require('../db/database');
const { rateLimit } = require('rate-limiter-flexible');
const { similarity } = require('string-similarity');
const fs = require('fs').promises;

// Rate limiter (1 request per second per domain)
const rateLimiter = new rateLimit.RateLimiterMemory({
  points: 1,
  duration: 1,
});

// Job tracking
const jobs = new Map();

const startScraping = async (req, res) => {
  try {
    const { ingredients } = req.body;
    
    if (!ingredients || !Array.isArray(ingredients) || ingredients.length === 0) {
      return res.status(400).json({ error: 'Ingredients array is required' });
    }
    
    // Generate job ID
    const jobId = Date.now().toString();
    jobs.set(jobId, { status: 'pending', progress: 0, total: 0, results: [] });
    
    // Start scraping in background
    processScraping(jobId, ingredients);
    
    res.json({ jobId, status: 'started' });
  } catch (error) {
    console.error('Error starting scraping:', error);
    res.status(500).json({ error: 'Error starting scraping' });
  }
};

const getJobStatus = async (req, res) => {
  const { id } = req.params;
  const job = jobs.get(id);
  
  if (!job) {
    return res.status(404).json({ error: 'Job not found' });
  }
  
  res.json(job);
};

const processScraping = async (jobId, ingredients) => {
  const job = jobs.get(jobId);
  if (!job) return;
  
  try {
    job.status = 'running';
    job.total = ingredients.length;
    
    // Generate search queries
    const searchQueries = generateSearchQueries(ingredients);
    
    // Process each query
    for (let i = 0; i < searchQueries.length; i++) {
      const query = searchQueries[i];
      const results = await searchRecipes(query);
      
      // Process results
      for (const result of results) {
        try {
          // Check if URL already exists
          const existing = await pool.query(
            'SELECT id FROM recipes WHERE url = $1',
            [result.url]
          );
          
          if (existing.rows.length > 0) {
            continue; // Skip if already exists
          }
          
          // Extract recipe with LLM
          const recipe = await extractRecipeWithLLM(result.html, result.url);
          
          // Save to database
          await saveRecipe(recipe);
          
          job.results.push(recipe);
        } catch (error) {
          console.error('Error processing recipe:', error);
        }
      }
      
      job.progress = i + 1;
      jobs.set(jobId, job);
    }
    
    job.status = 'done';
    jobs.set(jobId, job);
  } catch (error) {
    console.error('Error in scraping process:', error);
    job.status = 'error';
    job.error = error.message;
    jobs.set(jobId, job);
  }
};

const generateSearchQueries = (ingredients) => {
  // Simple query generation - could be improved with more complex logic
  const keywords = ['ricetta', 'con', 'preparazione'];
  const queries = [];
  
  // Combine ingredients with keywords
  for (let i = 1; i <= Math.min(3, ingredients.length); i++) {
    const combo = ingredients.slice(0, i).join(' ');
    for (const keyword of keywords) {
      queries.push(`${combo} ${keyword}`);
    }
  }
  
  // Add generic queries
  queries.push(...ingredients.map(ing => `${ing} ricetta`));
  
  return [...new Set(queries)]; // Remove duplicates
};

const searchRecipes = async (query) => {
  // This is a simplified version - in practice, you'd use a proper search API
  // For now, we'll simulate results
  const results = [];
  
  // Simulate search results
  for (let i = 0; i < 3; i++) {
    results.push({
      url: `https://example.com/recipe-${Date.now()}-${i}`,
      html: `<html><head><title>${query}</title></head><body><h1>${query}</h1><p>Sample recipe content for ${query}</p></body></html>`
    });
  }
  
  return results;
};

const extractRecipeWithLLM = async (html, url) => {
  // In a real implementation, this would call Open WebUI or Ollama
  // For now, we'll simulate the LLM response with a mock function
  
  const $ = cheerio.load(html);
  const title = $('title').text() || $('h1').first().text() || 'Untitled Recipe';
  
  // Mock response - in reality, this would come from the LLM
  return {
    title: title,
    url: url,
    ingredients: [
      { raw: "uova", name: "uova", quantity: 4, unit: "pz", notes: "" },
      { raw: "farina", name: "farina", quantity: 200, unit: "g", notes: "" }
    ],
    steps: [
      "Prendi le uova