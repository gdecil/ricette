const { Pool } = require('pg');
const dotenv = require('dotenv');

dotenv.config();

const pool = new Pool({
  connectionString: process.env.DATABASE_URL
});

const initDB = async () => {
  const client = await pool.connect();
  
  try {
    // Create categories table
    await client.query(`
      CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE
      )
    `);
    
    // Create recipes table
    await client.query(`
      CREATE TABLE IF NOT EXISTS recipes (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        url TEXT UNIQUE NOT NULL,
        summary TEXT,
        prep_time_min INTEGER,
        cook_time_min INTEGER,
        total_time_min INTEGER,
        servings INTEGER,
        calories INTEGER,
        difficulty TEXT,
        cuisine TEXT,
        language TEXT,
        completeness_score FLOAT,
        confidence FLOAT,
        created_at TIMESTAMP DEFAULT now(),
        updated_at TIMESTAMP DEFAULT now()
      )
    `);
    
    // Create ingredients table
    await client.query(`
      CREATE TABLE IF NOT EXISTS ingredients (
        id SERIAL PRIMARY KEY,
        name TEXT UNIQUE,
        created_at TIMESTAMP DEFAULT now()
      )
    `);
    
    // Create recipe_ingredients table
    await client.query(`
      CREATE TABLE IF NOT EXISTS recipe_ingredients (
        id SERIAL PRIMARY KEY,
        recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
        ingredient_id INTEGER REFERENCES ingredients(id) ON DELETE SET NULL,
        raw TEXT,
        quantity FLOAT,
        unit TEXT,
        notes TEXT
      )
    `);
    
    // Create steps table
    await client.query(`
      CREATE TABLE IF NOT EXISTS steps (
        id SERIAL PRIMARY KEY,
        recipe_id INTEGER REFERENCES recipes(id) ON DELETE CASCADE,
        step_index INTEGER,
        text TEXT
      )
    `);
    
    // Insert default categories
    const categories = ['antipasti', 'primi', 'secondi', 'contorni', 'dolci', 'bevande', 'altro'];
    for (const category of categories) {
      await client.query(
        `INSERT INTO categories (name) VALUES ($1) ON CONFLICT (name) DO NOTHING`,
        [category]
      );
    }
    
    console.log('Database initialized successfully');
  } catch (err) {
    console.error('Error initializing database:', err);
  } finally {
    client.release();
  }
};

module.exports = { pool, initDB };