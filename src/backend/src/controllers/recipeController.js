const { pool } = require('../db/database');

const getAllRecipes = async (req, res) => {
  try {
    const { page = 1, limit = 10, category, ingredient, minTime, maxTime, minCalories, maxCalories } = req.query;
    const offset = (page - 1) * limit;
    
    let query = `
      SELECT r.*, c.name as category_name
      FROM recipes r
      LEFT JOIN categories c ON r.category_id = c.id
      WHERE 1=1
    `;
    const params = [];
    
    if (category) {
      query += ` AND c.name = $${params.length + 1}`;
      params.push(category);
    }
    
    if (ingredient) {
      query += ` AND r.id IN (SELECT recipe_id FROM recipe_ingredients ri JOIN ingredients i ON ri.ingredient_id = i.id WHERE i.name ILIKE $${params.length + 1})`;
      params.push(`%${ingredient}%`);
    }
    
    if (minTime) {
      query += ` AND r.total_time_min >= $${params.length + 1}`;
      params.push(parseInt(minTime));
    }
    
    if (maxTime) {
      query += ` AND r.total_time_min <= $${params.length + 1}`;
      params.push(parseInt(maxTime));
    }
    
    if (minCalories) {
      query += ` AND r.calories >= $${params.length + 1}`;
      params.push(parseInt(minCalories));
    }
    
    if (maxCalories) {
      query += ` AND r.calories <= $${params.length + 1}`;
      params.push(parseInt(maxCalories));
    }
    
    query += ` ORDER BY r.created_at DESC LIMIT $${params.length + 1} OFFSET $${params.length + 2}`;
    params.push(parseInt(limit), parseInt(offset));
    
    const result = await pool.query(query, params);
    
    res.json({
      recipes: result.rows,
      pagination: {
        page: parseInt(page),
        limit: parseInt(limit),
        total: result.rows.length
      }
    });
  } catch (error) {
    console.error('Error fetching recipes:', error);
    res.status(500).json({ error: 'Error fetching recipes' });
  }
};

const getRecipeById = async (req, res) => {
  try {
    const { id } = req.params;
    const result = await pool.query(
      `SELECT r.*, c.name as category_name
       FROM recipes r
       LEFT JOIN categories c ON r.category_id = c.id
       WHERE r.id = $1`,
      [id]
    );
    
    if (result.rows.length === 0) {
      return res.status(404).json({ error: 'Recipe not found' });
    }
    
    const recipe = result.rows[0];
    
    // Get ingredients
    const ingredientsResult = await pool.query(
      `SELECT ri.*, i.name as ingredient_name
       FROM recipe_ingredients ri
       JOIN ingredients i ON ri.ingredient_id = i.id
       WHERE ri.recipe_id = $1
       ORDER BY ri.id`,
      [id]
    );
    
    // Get steps
    const stepsResult = await pool.query(
      `SELECT * FROM steps WHERE recipe_id = $1 ORDER BY step_index`,
      [id]
    );
    
    recipe.ingredients = ingredientsResult.rows;
    recipe.steps = stepsResult.rows.map(step => step.text);
    
    res.json(recipe);
  } catch (error) {
    console.error('Error fetching recipe:', error);
    res.status(500).json({ error: 'Error fetching recipe' });
  }
};

const importRecipe = async (req, res) => {
  try {
    const recipeData = req.body;
    
    // Validate required fields
    if (!recipeData.title || !recipeData.url) {
      return res.status(400).json({ error: 'Title and URL are required' });
    }
    
    // Insert recipe
    const result = await pool.query(
      `INSERT INTO recipes 
       (title, url, summary, prep_time_min, cook_time_min, total_time_min, servings, calories, difficulty, cuisine, language, completeness_score, confidence)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
       RETURNING id`,
      [
        recipeData.title,
        recipeData.url,
        recipeData.summary,
        recipeData.prep_time_min,
        recipeData.cook_time_min,
        recipeData.total_time_min,
        recipeData.servings,
        recipeData.calories,
        recipeData.difficulty,
        recipeData.cuisine,
        recipeData.language,
        recipeData.completeness_score,
        recipeData.confidence
      ]
    );
    
    const recipeId = result.rows[0].id;
    
    // Insert ingredients
    if (recipeData.ingredients && recipeData.ingredients.length > 0) {
      for (const ingredient of recipeData.ingredients) {
        // Check if ingredient exists
        let ingredientId = await pool.query(
          'SELECT id FROM ingredients WHERE name = $1',
          [ingredient.name]
        );
        
        if (ingredientId.rows.length === 0) {
          // Insert new ingredient
          const newIngredient = await pool.query(
            'INSERT INTO ingredients (name) VALUES ($1) RETURNING id',
            [ingredient.name]
          );
          ingredientId = newIngredient.rows[0].id;
        } else {
          ingredientId = ingredientId.rows[0].id;
        }
        
        // Insert recipe_ingredient
        await pool.query(
          'INSERT INTO recipe_ingredients (recipe_id, ingredient_id, raw, quantity, unit, notes) VALUES ($1, $2, $3, $4, $5, $6)',
          [recipeId, ingredientId, ingredient.raw, ingredient.quantity, ingredient.unit, ingredient.notes]
        );
      }
    }
    
    // Insert steps
    if (recipeData.steps && recipeData.steps.length > 0) {
      for (let i = 0; i < recipeData.steps.length; i++) {
        await pool.query(
          'INSERT INTO steps (recipe_id, step_index, text) VALUES ($1, $2, $3)',
          [recipeId, i, recipeData.steps[i]]
        );
      }
    }
    
    res.json({ id: recipeId, message: 'Recipe imported successfully' });
  } catch (error) {
    console.error('Error importing recipe:', error);
    res.status(500).json({ error: 'Error importing recipe' });
  }
};

const deleteRecipe = async (req, res) => {
  try {
    const { id } = req.params;
    
    await pool.query('DELETE FROM recipes WHERE id = $1', [id]);
    
    res.json({ message: 'Recipe deleted successfully' });
  } catch (error) {
    console.error('Error deleting recipe:', error);
    res.status(500).json({ error: 'Error deleting recipe' });
  }
};

module.exports = {
  getAllRecipes,
  getRecipeById,
  importRecipe,
  deleteRecipe
};