const axios = require('axios');
require('dotenv').config();

const OLLAMA_URL = process.env.OLLAMA_URL || 'http://localhost:11434';

/**
 * Extract recipe information from raw text using Ollama AI
 * @param {string} rawText - Raw text content from the webpage
 * @param {string} url - Source URL of the recipe
 * @returns {object} Extracted recipe information
 */
const extractRecipeInfo = async (rawText, url) => {
  try {
    // Check if Ollama is available
    try {
      await axios.get(`${OLLAMA_URL}/api/tags`, { timeout: 5000 });
    } catch (err) {
      console.warn('Ollama is not available. Using fallback extraction.');
      return null;
    }

    const prompt = `You are a helpful assistant that extracts structured recipe information from web content.
Extract the following information from the provided text:

1. Title - The name of the recipe
2. Ingredients - A list of all ingredients with measurements
3. Instructions - Step-by-step cooking instructions
4. Prep Time - Time needed to prepare (in minutes, extract number only)
5. Cook Time - Time needed to cook (in minutes, extract number only)
6. Servings - Number of servings the recipe makes
7. Difficulty - Easy, Medium, or Hard
8. Category - Main dish, Side dish, Dessert, Soup, Salad, etc.

Return ONLY a valid JSON object with the following structure (no markdown, no extra text):
{
  "title": "Recipe name",
  "ingredients": ["ingredient 1", "ingredient 2"],
  "instructions": ["step 1", "step 2"],
  "prep_time": 15,
  "cook_time": 30,
  "servings": 4,
  "difficulty": "Medium",
  "category": "Main dish"
}

If information is not available in the text, use null for that field.

Here is the text to analyze:
${rawText.substring(0, 4000)}`;

    const response = await axios.post(
      `${OLLAMA_URL}/api/generate`,
      {
        model: process.env.OLLAMA_MODEL || 'llama3',
        prompt: prompt,
        stream: false
      },
      {
        timeout: 30000
      }
    );

    // Parse the JSON from response
    let result = response.data.response;
    
    // Try to extract JSON from response if it's wrapped in markdown or text
    if (result.includes('```json')) {
      const jsonMatch = result.match(/```json([\s\S]*?)```/);
      if (jsonMatch) {
        result = jsonMatch[1];
      }
    } else if (result.includes('```')) {
      const jsonMatch = result.match(/```([\s\S]*?)```/);
      if (jsonMatch) {
        result = jsonMatch[1];
      }
    }
    
    // Find first { and last } to extract JSON object
    const firstBrace = result.indexOf('{');
    const lastBrace = result.lastIndexOf('}');
    if (firstBrace !== -1 && lastBrace !== -1) {
      result = result.substring(firstBrace, lastBrace + 1);
    }
    
    const extracted = JSON.parse(result.trim());
    
    return {
      title: extracted.title || 'Unknown Recipe',
      ingredients: Array.isArray(extracted.ingredients) ? extracted.ingredients : [],
      instructions: Array.isArray(extracted.instructions) ? extracted.instructions : [],
      prep_time: extracted.prep_time || null,
      cook_time: extracted.cook_time || null,
      servings: extracted.servings || null,
      difficulty: extracted.difficulty || null,
      category: extracted.category || 'Uncategorized',
      url: url
    };

  } catch (err) {
    console.error('Error extracting recipe info with Ollama:', err.message);
    return null;
  }
};

/**
 * Fallback extraction method using simple regex patterns
 * @param {string} rawText - Raw text content from the webpage
 * @param {string} url - Source URL of the recipe
 * @returns {object} Extracted recipe information
 */
const fallbackExtract = (rawText, url) => {
  // Simple heuristics for extraction
  const sentences = rawText.split(/[.!?]+/);
  
  // Look for ingredient-related keywords
  const ingredients = [];
  const ingredientKeywords = ['cup', 'tablespoon', 'teaspoon', 'ounce', 'pound', 'gram', 'kilogram', 'liter', 'ml', 'oz', 'lb', 'g', 'kg', 'ml', 'cucchiaio', 'cucchiaino', 'grammi'];
  
  sentences.forEach(sentence => {
    const trimmed = sentence.trim();
    if (ingredientKeywords.some(keyword => trimmed.toLowerCase().includes(keyword)) && trimmed.length < 200) {
      ingredients.push(trimmed);
    }
  });

  // Find longest sentences as instructions
  const sorted = sentences.sort((a, b) => b.length - a.length);
  const instructions = sorted.slice(0, 10).map(s => s.trim()).filter(s => s.length > 20);

  return {
    title: 'Extracted Recipe',
    ingredients: ingredients.slice(0, 20),
    instructions: instructions,
    prep_time: null,
    cook_time: null,
    servings: null,
    difficulty: null,
    category: 'Uncategorized',
    url: url
  };
};

module.exports = {
  extractRecipeInfo,
  fallbackExtract
};